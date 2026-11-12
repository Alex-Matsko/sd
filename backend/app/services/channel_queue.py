"""PostgreSQL-backed channel jobs; no broker is required.

Transactions protect local state. External transports are at-least-once:
SMTP/Telegram/MAX cannot atomically commit together with our database.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from sqlalchemy import and_, exists, inspect, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.core.enums import Channel, MessageDirection, NotificationType, UserRole
from app.models.channel_job import ChannelJob
from app.models.message import Attachment, Message
from app.models.notification import Notification
from app.models.user import User

MAX_ATTEMPTS = 8
LEASE_SECONDS = 300
TERMINAL = ("sent", "processed", "discarded")
_current: ContextVar[tuple[Session, int, list[int]] | None] = ContextVar("channel_transaction", default=None)


class ChannelFailure(RuntimeError):
    """Safe, operator-facing error; never include credentials or remote bodies."""


class PermanentChannelFailure(ChannelFailure):
    pass


def now():
    return datetime.now(timezone.utc)


def safe_error(error: Exception) -> str:
    from app.services.attachments import AttachmentTooLarge
    if isinstance(error, (ChannelFailure, AttachmentTooLarge)):
        return str(error)[:500]
    return f"Ошибка обработки ({type(error).__name__}). Проверьте доступность канала и его настройки."


def notify_operators(db: Session, title: str, ticket_id: int | None = None):
    from app.services.realtime import publish_notification
    for user in db.query(User).filter(User.is_active.is_(True), User.role.in_([UserRole.ADMIN, UserRole.MANAGER])):
        db.add(Notification(user_id=user.id, ticket_id=ticket_id, type=NotificationType.CHANNEL_ERROR, title=title[:500]))
        publish_notification(db, user.id, NotificationType.CHANNEL_ERROR.value, title[:500], ticket_id)


def capture(db: Session, channel: str, event_key: str, stream_key: str, payload: dict, raw_body: bytes | None = None):
    statement = insert(ChannelJob).values(
        kind="inbound", channel=channel, event_key=event_key, stream_key=stream_key,
        payload=payload, raw_body=raw_body, state="pending", attempts=0,
    ).on_conflict_do_nothing(index_elements=[ChannelJob.event_key]).returning(ChannelJob.id)
    job_id = db.execute(statement).scalar()
    db.commit()  # confirmation/cursor advancement is allowed only after this durable write
    return job_id


def capture_update(db: Session, channel: Channel, update: dict, config):
    from app.services import max_channel, telegram_channel
    module = telegram_channel if channel == Channel.TELEGRAM else max_channel
    parsed = module._extract_incoming(update)
    # The whole provider event is hashed, covering callbacks and events with no message id.
    digest = hashlib.sha256(json.dumps(update, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    account = hashlib.sha256(f"{config.base_url}:{config.token}".encode()).hexdigest()[:20]
    identity = str(update.get("update_id", digest))
    stream = f"{channel.value}:{account}:{parsed.chat_id if parsed else digest}"[:128]
    return capture(db, channel.value, f"{channel.value}:{account}:{identity}", stream,
                   {**update, "_sd_summary": (parsed.text or "Событие бота")[:180] if parsed else "Служебное событие"})


def enqueue_message(db: Session, message: Message):
    from app.services import max_channel, telegram_channel
    existing = db.query(ChannelJob).filter_by(message_id=message.id, kind="outbound").first()
    if existing is not None:
        return existing
    ticket = message.ticket
    payload = {"contact_id": ticket.contact_id, "organization_id": ticket.organization_id, "_sd_summary": message.body[:180], "attachment_ids": [item.id for item in message.attachments]}
    if message.channel == Channel.EMAIL:
        contact = ticket.contact
        if contact and contact.emails:
            payload["recipient"] = next((e.email for e in contact.emails if e.is_primary), contact.emails[0].email)
    else:
        module = telegram_channel if message.channel == Channel.TELEGRAM else max_channel
        state = module._find_chat_state(db, ticket.contact_id)
        if state:
            payload["recipient"] = state.chat_id
    job = ChannelJob(kind="outbound", channel=message.channel.value, event_key=f"message:{message.id}",
                     stream_key=f"{message.channel.value}:chat:{payload['recipient']}" if payload.get("recipient") else f"{message.channel.value}:contact:{ticket.contact_id}", payload=payload,
                     message_id=message.id, ticket_id=message.ticket_id)
    db.add(job)
    return job


@contextmanager
def queued_bot_replies(db: Session, event_id: int):
    token = _current.set((db, event_id, [0]))
    try:
        yield
    finally:
        _current.reset(token)


def defer_bot_reply(channel: str, chat_id: str, text: str, buttons=None, reply_to=None) -> bool:
    context = _current.get()
    if context is None:
        return False
    db, event_id, counter = context
    counter[0] += 1
    db.add(ChannelJob(kind="outbound", channel=channel,
                      event_key=f"event:{event_id}:reply:{counter[0]}", stream_key=f"{channel}:chat:{chat_id}",
                      payload={"recipient": chat_id, "text": text, "buttons": buttons, "reply_to": reply_to}))
    return True


def claim(db: Session, kind: str, job_id: int | None = None):
    clock = now()
    earlier = aliased(ChannelJob)
    ready = or_(and_(ChannelJob.state.in_(["pending", "retry"]), ChannelJob.available_at <= clock),
                and_(ChannelJob.state == "processing", ChannelJob.lease_until < clock))
    # Never advance a conversation past an unresolved earlier event/message.
    blocked = exists(select(earlier.id).where(
        earlier.kind == ChannelJob.kind, earlier.stream_key == ChannelJob.stream_key,
        earlier.id < ChannelJob.id, earlier.state.notin_(TERMINAL),
    ))
    query = db.query(ChannelJob).filter(ChannelJob.kind == kind, ready, ~blocked)
    if job_id is not None:
        query = query.filter(ChannelJob.id == job_id)
    job = query.order_by(ChannelJob.id).with_for_update(skip_locked=True).first()
    if job is None:
        db.rollback()
        return None
    job.state = "processing"
    job.attempts += 1
    job.lease_token = str(uuid.uuid4())
    job.lease_until = clock + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    return job.id, job.lease_token


def fail(db: Session, job_id: int, lease_token: str, error: Exception):
    db.rollback()
    job = db.query(ChannelJob).filter_by(id=job_id, lease_token=lease_token, state="processing").with_for_update().first()
    if job is None:
        return
    from app.services.attachments import AttachmentTooLarge
    job.last_error = safe_error(error)
    job.state = "failed" if isinstance(error, (PermanentChannelFailure, AttachmentTooLarge)) or job.attempts >= MAX_ATTEMPTS else "retry"
    job.available_at = now() + timedelta(seconds=min(10 * 2 ** (job.attempts - 1), 3600))
    job.lease_until = None
    job.lease_token = None
    if job.attempts == 1 or job.state == "failed":
        notify_operators(db, f"Канал {job.channel}: {job.last_error}", job.ticket_id)
    db.commit()


def retry(db: Session, job: ChannelJob):
    if job.state not in ("failed", "retry"):
        raise ValueError("Повтор возможен только для сообщения с ошибкой")
    job.state = "pending"
    job.attempts = 0
    job.available_at = now()
    job.lease_until = None
    job.lease_token = None
    job.last_error = None
    db.commit()


class DeferredCommitSession(Session):
    """Legacy ingestion services may commit; inside a journal event these only flush.

    The caller explicitly uses Session.commit(unit) to release its savepoint
    after the event and all its effects have been recorded together.
    """
    def add(self, instance, _warn=True):
        # A later download can fail before the pending attachment is flushed.
        # Remember its new file now so the failed event also removes that file.
        if isinstance(instance, Attachment) and inspect(instance).transient:
            self.info.setdefault("created_files", set()).add(instance.stored_path)
        return super().add(instance, _warn=_warn)

    def flush(self, objects=None):
        paths = self.info.setdefault("created_files", set())
        paths.update(item.stored_path for item in self.new if isinstance(item, Attachment))
        return super().flush(objects)

    def commit(self):
        self.flush()


def process_inbound(db: Session, job_id: int, lease_token: str):
    from app.services import email_channel, max_channel, telegram_channel
    released = False
    unit = None
    try:
        with DeferredCommitSession(bind=db.connection(), join_transaction_mode="create_savepoint") as unit:
            job = unit.query(ChannelJob).filter_by(id=job_id, lease_token=lease_token, state="processing").with_for_update().one()
            with queued_bot_replies(unit, job.id):
                if job.channel == "email":
                    if job.raw_body is None and job.payload.get("_source_oversized"):
                        job.raw_body = email_channel.retrieve_captured_email(unit, job)
                    result = email_channel.ingest_email(unit, job.raw_body)
                    job.ticket_id = result.ticket.id
                else:
                    module = telegram_channel if job.channel == "telegram" else max_channel
                    config = module.load_telegram_config(unit) if job.channel == "telegram" else module.load_max_config(unit)
                    if config is None:
                        raise ChannelFailure("Канал отключён или не настроен")
                    module.handle_update(unit, job.payload)
                    parsed = module._extract_incoming(job.payload)
                    if parsed:
                        from app.models.channel_conversation_state import ChannelConversationState
                        state = unit.query(ChannelConversationState).filter_by(channel=Channel(job.channel), external_user_id=parsed.external_user_id).first()
                        job.ticket_id = state.active_ticket_id if state else None
                        if job.ticket_id:
                            for reply in unit.query(ChannelJob).filter(ChannelJob.event_key.like(f"event:{job.id}:reply:%")):
                                reply.ticket_id = job.ticket_id
            job.state, job.completed_at, job.last_error = "processed", now(), None
            job.lease_until, job.lease_token = None, None
            Session.commit(unit)
            released = True
        db.commit()
        db.expire_all()
        return True
    except Exception as error:
        if unit is not None and not released:
            from pathlib import Path
            for path in unit.info.get("created_files", ()):
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
        fail(db, job_id, lease_token, error)
        return False


def process_outbound(db: Session, job_id: int, lease_token: str):
    from app.services.channel_transport import send_job
    try:
        # Held across transport calls: other workers skip the locked job even
        # if a slow provider call outlives its lease.
        job = db.query(ChannelJob).filter_by(id=job_id, lease_token=lease_token, state="processing").with_for_update().one()
        delivered = send_job(db, job)
        job.state, job.completed_at, job.last_error = "discarded" if delivered is False else "sent", now(), None
        job.lease_until, job.lease_token = None, None
        db.commit()
        return True
    except Exception as error:
        fail(db, job_id, lease_token, error)
        return False


def run_batch(db: Session, kind: str, limit=20):
    count = 0
    for _ in range(limit):
        claimed = claim(db, kind)
        if claimed is None:
            break
        processor = process_inbound if kind == "inbound" else process_outbound
        processor(db, *claimed)
        count += 1
    return count


def prune_completed(db: Session):
    from app.config import settings
    cutoff = now() - timedelta(days=settings.channel_event_retention_days)
    # Keep deduplication keys and audit metadata; raw customer content and
    # transient upload tokens need not accumulate forever after completion.
    jobs = db.query(ChannelJob).filter(ChannelJob.state.in_(TERMINAL), ChannelJob.completed_at < cutoff,
                                      ChannelJob.raw_body.isnot(None) | (ChannelJob.payload["_source_expired"].as_boolean().isnot(True)))
    count = 0
    for job in jobs.limit(200):
        job.raw_body = None
        job.payload = {"_sd_summary": job.payload.get("_sd_summary", ""), "_source_expired": True}
        count += 1
    db.commit()
    return count


def enqueue_notification(db, channel: str, recipient: str, text: str, *, buttons=None, ticket=None):
    payload = {"recipient": recipient, "text": text, "buttons": buttons, "_sd_summary": text[:180]}
    if ticket is not None:
        payload.update(contact_id=ticket.contact_id, organization_id=ticket.organization_id)
    job = ChannelJob(kind="outbound", channel=channel, event_key=f"notice:{uuid.uuid4()}",
                     stream_key=f"{channel}:chat:{recipient}", payload=payload,
                     ticket_id=ticket.id if ticket is not None else None)
    db.add(job)
    return job
