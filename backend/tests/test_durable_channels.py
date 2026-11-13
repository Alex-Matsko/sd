"""Failure injection across the durable inbox, outbox, and multipart API.

All transport calls stay local or mocked. No customer/bot credentials are used.
"""
from datetime import timedelta
from email.message import EmailMessage
from types import SimpleNamespace
from uuid import uuid4
import smtplib

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import Channel, MessageDirection, Priority, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.channel_job import ChannelJob, WorkerPulse
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import ContactEmail
from app.models.message import Attachment, Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import channel_queue as queue, email_channel, messages, telegram_channel, telegram_client, tickets, worker_health


@pytest.fixture()
def actor(db):
    return db.query(User).filter(User.role == UserRole.ADMIN).first()


def make_ticket(db, contact, channel=Channel.EMAIL):
    return tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT,
        channel=channel, subject="Проверка надёжной доставки", manual_priority=Priority.P3,
        manual_priority_reason="Проверка"), actor=None)


def email_raw(sender="sender@example.org", message_id="<durable-test@example.org>"):
    mail = EmailMessage()
    mail["From"], mail["To"], mail["Subject"], mail["Message-ID"] = sender, "support@example.org", "Тест надёжности", message_id
    mail.set_content("Не работает доступ")
    mail.add_attachment(b"inbound file", maintype="text", subtype="plain", filename="screen.txt")
    return mail.as_bytes()


def ready(db, job):
    job.available_at = queue.now() - timedelta(seconds=1)
    db.commit()


def test_outbound_is_persisted_atomically_and_request_retry_does_not_duplicate(db, contact, actor, tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    db.add(ContactEmail(contact_id=contact.id, email="queue@example.org", is_primary=True)); db.commit()
    ticket = make_ticket(db, contact)
    payload = MessageCreate(direction=MessageDirection.OUTBOUND, body="Ответ", request_id=uuid4())
    files = [("test.txt", b"attachment", "text/plain")]
    first = messages.add_message(db, ticket, payload, author_user=actor, attachments=files)
    second = messages.add_message(db, ticket, payload, author_user=actor, attachments=files)
    assert first.id == second.id
    job = db.query(ChannelJob).filter_by(message_id=first.id).one()
    assert job.state == "pending" and job.payload["recipient"] == "queue@example.org"
    assert len(first.attachments) == 1
    assert job.payload["attachment_ids"] == [first.attachments[0].id]
    assert ticket.first_response_at is None
    with pytest.raises(messages.RequestConflict):
        messages.add_message(db, ticket, payload.model_copy(update={"body": "Другой текст"}), author_user=actor, attachments=files)


def test_failed_smtp_is_visible_and_retry_preserves_message_id_and_sla(db, contact, actor, monkeypatch):
    from app.services.email_channel import EmailConfig
    config = EmailConfig(imap_host="unused", imap_port=993, imap_use_ssl=True, imap_username="test", imap_password="test",
        imap_folder="INBOX", smtp_host="localhost", smtp_port=25, smtp_use_tls=False, smtp_username="", smtp_password="",
        from_address="support@example.org", from_display_name="Support", poll_interval_seconds=30)
    monkeypatch.setattr(email_channel, "load_email_config", lambda db: config)
    db.add(ContactEmail(contact_id=contact.id, email="delivery@example.org", is_primary=True)); db.commit()
    ticket = make_ticket(db, contact)
    message = messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Ответ"), author_user=actor)
    sent = []
    def temporary_failure(*args, **kwargs):
        raise smtplib.SMTPConnectError(451, b"secret-token-that-must-not-be-exposed")
    monkeypatch.setattr(email_channel, "send_outbound_email", temporary_failure)
    claimed = queue.claim(db, "outbound", message.delivery.id)
    assert queue.process_outbound(db, *claimed) is False
    db.refresh(message)
    job = message.delivery
    assert job.state == "retry" and job.attempts == 1
    assert "secret-token" not in job.last_error
    assert ticket.first_response_at is None
    stable_id = job.payload["email_message_id"]
    monkeypatch.setattr(email_channel, "send_outbound_email", lambda *a, **kw: sent.append(kw))
    ready(db, job)
    assert queue.process_outbound(db, *queue.claim(db, "outbound", job.id)) is True
    db.refresh(job); db.refresh(ticket); db.refresh(message)
    assert job.state == "sent" and job.attempts == 2
    assert message.email_message_id == stable_id == sent[0]["message_id"]
    assert ticket.first_response_at is not None
    assert queue.claim(db, "outbound", job.id) is None


def test_partial_bot_delivery_retries_only_unsent_files(db, contact, actor, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    config = SimpleNamespace(base_url="http://local-test", token="test")
    monkeypatch.setattr(telegram_channel, "load_telegram_config", lambda db: config)
    texts, files = [], []
    monkeypatch.setattr(telegram_client, "send_message", lambda *a, **kw: texts.append(a[3]) or {"message_id": len(texts)})
    db.add(ChannelConversationState(channel=Channel.TELEGRAM, external_user_id="test", chat_id="42", contact_id=contact.id)); db.commit()
    ticket = make_ticket(db, contact, Channel.TELEGRAM)
    message = messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Ответ"), author_user=actor,
                                  attachments=[("one.txt", b"1", "text/plain"), ("two.txt", b"2", "text/plain")])
    texts.clear()
    first_attempt = True
    def send_file(base, token, chat, name, content, mime):
        if name == "two.txt" and first_attempt:
            raise RuntimeError("network down")
        files.append(name)
        return {"message_id": 10 + len(files)}
    monkeypatch.setattr(telegram_client, "send_document", send_file)
    job_id = message.delivery.id
    assert queue.process_outbound(db, *queue.claim(db, "outbound", job_id)) is False
    first_attempt = False
    job = db.get(ChannelJob, job_id); ready(db, job)
    assert queue.process_outbound(db, *queue.claim(db, "outbound", job_id)) is True
    assert texts == [f"Заявка {ticket.display_number} — {ticket.subject}\n\nОтвет"]
    assert files == ["one.txt", "two.txt"]


def test_failed_inbound_rolls_back_all_effects_and_can_be_replayed(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    raw = email_raw()
    job_id = queue.capture(db, "email", f"test:{uuid4()}", "test-inbound", {}, raw)
    initial_tickets = db.query(Ticket).count()
    ingest = email_channel.ingest_email
    def fail_after_ingest(unit, raw):
        ingest(unit, raw)
        raise RuntimeError("crash after creating message")
    monkeypatch.setattr(email_channel, "ingest_email", fail_after_ingest)
    assert queue.process_inbound(db, *queue.claim(db, "inbound", job_id)) is False
    assert db.query(Ticket).count() == initial_tickets
    assert list(tmp_path.rglob("*.txt")) == []
    job = db.get(ChannelJob, job_id)
    assert job.state == "retry" and job.raw_body == raw
    monkeypatch.setattr(email_channel, "ingest_email", ingest)
    ready(db, job)
    assert queue.process_inbound(db, *queue.claim(db, "inbound", job_id)) is True
    assert db.query(Ticket).count() == initial_tickets + 1
    assert db.get(ChannelJob, job_id).state == "processed"
    assert db.query(Message).filter(Message.email_message_id == "<durable-test@example.org>").count() == 1
    assert queue.capture(db, "email", job.event_key, "test-inbound", {}, email_raw()) is None


def test_mailbox_validity_reset_does_not_create_a_second_message(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    for validity in ("old", "new"):
        job_id = queue.capture(db, "email", f"test:{validity}:{uuid4()}", "mailbox", {}, email_raw())
        assert queue.process_inbound(db, *queue.claim(db, "inbound", job_id)) is True
    assert db.query(Message).filter_by(email_message_id="<durable-test@example.org>").count() == 1


def test_stream_order_and_expired_lease_recovery(db):
    first = queue.capture(db, "email", f"test:{uuid4()}", "ordered", {}, b"one")
    second = queue.capture(db, "email", f"test:{uuid4()}", "ordered", {}, b"two")
    claimed = queue.claim(db, "inbound", first)
    assert queue.claim(db, "inbound", second) is None
    row = db.get(ChannelJob, first)
    row.lease_until = queue.now() - timedelta(seconds=1); db.commit()
    recovered = queue.claim(db, "inbound", first)
    assert recovered[0] == first and recovered[1] != claimed[1]
    queue.fail(db, first, claimed[1], RuntimeError("stale worker"))
    assert db.get(ChannelJob, first).lease_token == recovered[1]


def test_health_tracks_failure_disabled_components_and_staleness(db):
    worker_health.pulse(db, "main", success=True, interval=5)
    worker_health.pulse(db, "email", error=TimeoutError("private"), interval=30)
    states = {row["component"]: row for row in worker_health.snapshot(db)}
    assert states["main"]["state"] == "ok"
    assert states["email"]["state"] == "error" and "private" not in states["email"]["last_error"]
    worker_health.pulse(db, "email", success=True, enabled=False)
    assert next(r for r in worker_health.snapshot(db) if r["component"] == "email")["state"] == "disabled"
    assert next(r for r in worker_health.snapshot(db, queue.now() + timedelta(minutes=5)) if r["component"] == "main")["state"] == "stale"


def test_atomic_api_enforces_access_and_file_limit_without_partial_messages(db, contact, actor, engineer_user, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    monkeypatch.setattr("app.config.settings.default_ticket_attachment_limit_mb", 0)
    ticket = make_ticket(db, contact)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    try:
        with TestClient(app) as client:
            result = client.post(f"/tickets/{ticket.id}/messages/send", data={"payload": '{"direction":"outbound","body":"reply","channel":"portal"}'},
                                 files={"files": ("big.txt", b"x", "text/plain")})
            assert result.status_code == 413
            assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0
            app.dependency_overrides[get_current_user] = lambda: engineer_user
            assert client.get("/operations/status").status_code == 403
            assert client.get("/operations/jobs").status_code == 403
    finally:
        app.dependency_overrides = previous


def test_poll_does_not_ack_until_event_is_saved_and_does_not_duplicate_a_batch(db, monkeypatch):
    from app.services import telegram_channel
    config = SimpleNamespace(base_url="http://local-test", token="test", poll_timeout_seconds=1)
    updates = [{"update_id": n, "message": {"message_id": n, "from": {"id": 42}, "chat": {"id": 42, "type": "private"}, "text": "hello"}} for n in (1, 2)]
    monkeypatch.setattr(telegram_channel, "_ensure_commands_registered", lambda config: None)
    monkeypatch.setattr(telegram_client, "get_updates", lambda *a, **kw: updates)
    capture = queue.capture_update
    def fail_second(db, channel, update, config):
        if update["update_id"] == 2:
            raise RuntimeError("database unavailable")
        return capture(db, channel, update, config)
    monkeypatch.setattr(queue, "capture_update", fail_second)
    with pytest.raises(RuntimeError):
        telegram_channel.poll_updates(db, config)
    assert telegram_channel.get_offset(db) is None
    monkeypatch.setattr(queue, "capture_update", capture)
    assert telegram_channel.poll_updates(db, config) == 2
    assert telegram_channel.get_offset(db) == 3
    assert db.query(ChannelJob).filter_by(kind="inbound", channel="telegram").count() == 2


def test_watchdog_alerts_once_for_a_stalled_worker_and_recovers(db):
    from app.watchdog import sweep
    from app.models.notification import Notification
    worker_health.pulse(db, "main", success=True, interval=5)
    row = db.get(WorkerPulse, "main")
    row.succeeded_at = queue.now() - timedelta(minutes=10)
    db.commit()
    title = "Нет сигнала фоновой обработки: main"
    # Keep this incident independent of notifications left by a real local
    # worker/watchdog: old notices must predate the simulated last activity.
    db.query(Notification).filter_by(title=title).update({"created_at": row.succeeded_at - timedelta(seconds=1)})
    db.commit()
    before = db.query(Notification).filter_by(title=title).count()
    sweep(db, alert_missing=False)
    after = db.query(Notification).filter_by(title=title).count()
    assert after > before
    sweep(db, alert_missing=False)
    assert db.query(Notification).filter_by(title=title).count() == after
    worker_health.pulse(db, "main", success=True, interval=5)
    assert next(r for r in worker_health.snapshot(db) if r["component"] == "main")["state"] == "ok"


def test_retention_drops_only_completed_raw_data_and_preserves_deduplication(db):
    old = queue.now() - timedelta(days=30)
    done = queue.capture(db, "email", f"test:{uuid4()}", "done", {"_sd_summary": "summary"}, b"mail")
    failed = queue.capture(db, "email", f"test:{uuid4()}", "failed", {}, b"important unprocessed mail")
    row = db.get(ChannelJob, done); row.state = "processed"; row.completed_at = old
    db.get(ChannelJob, failed).state = "failed"
    db.commit()
    assert queue.prune_completed(db) >= 1
    db.refresh(row)
    assert row.raw_body is None and row.payload["_source_expired"] is True
    assert db.get(ChannelJob, failed).raw_body == b"important unprocessed mail"
    assert queue.capture(db, "email", row.event_key, "done", {}, b"duplicate") is None


def test_oversized_mail_remains_on_server_and_can_be_replayed_after_limit_change(db, monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    raw = email_raw()
    class Mailbox:
        seen = False
        def __init__(self, *args, **kwargs): pass
        def login(self, *args): pass
        def select(self, *args): return "OK", [b"1"]
        def response(self, *args): return "UIDVALIDITY", [b"77"]
        def uid(self, command, *args):
            if command == "search": return "OK", [b"" if self.seen else b"1"]
            if command == "fetch": return "OK", [(b"literal", raw[:email_channel.MAX_RAW_EMAIL_BYTES + 1])]
            if command == "store":
                Mailbox.seen = True
                return "OK", []
        def close(self): pass
        def logout(self): pass
    config = SimpleNamespace(imap_host="local", imap_port=143, imap_use_ssl=False, imap_username="user", imap_password="test", imap_folder="INBOX")
    monkeypatch.setattr(email_channel.imaplib, "IMAP4", Mailbox)
    monkeypatch.setattr(email_channel, "load_email_config", lambda db: config)
    monkeypatch.setattr(email_channel, "MAX_RAW_EMAIL_BYTES", 128)
    assert email_channel.poll_inbox(db, config) == 1
    job = db.query(ChannelJob).filter_by(kind="inbound").order_by(ChannelJob.id.desc()).first()
    assert job.raw_body is None and not Mailbox.seen
    assert not queue.process_inbound(db, *queue.claim(db, "inbound", job.id))
    db.refresh(job)
    assert job.state == "failed" and not Mailbox.seen
    monkeypatch.setattr(email_channel, "MAX_RAW_EMAIL_BYTES", 16384)
    queue.retry(db, job)
    assert queue.process_inbound(db, *queue.claim(db, "inbound", job.id))
    db.refresh(job)
    assert job.raw_body == raw
    email_channel.poll_inbox(db, config)
    assert Mailbox.seen


def test_bot_file_download_is_bounded_before_storing(monkeypatch):
    import httpx
    from app.services.attachments import AttachmentTooLarge, download_limited
    monkeypatch.setattr("app.config.settings.default_ticket_attachment_limit_mb", 0)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"large file"))) as client:
        with pytest.raises(AttachmentTooLarge):
            download_limited(client, "https://local-test/file")


@pytest.mark.parametrize("channel,runner", [(Channel.EMAIL, "run_email_poll"), (Channel.MAX, "run_max_poll_once"), (Channel.TELEGRAM, "run_telegram_poll_once")])
def test_enabled_but_unconfigured_channel_is_an_error_not_disabled(db, monkeypatch, channel, runner):
    from app import worker
    from app.services import integration_settings
    from app.schemas.integration_setting import IntegrationSettingUpdate
    integration_settings.upsert(db, channel, IntegrationSettingUpdate(is_enabled=True, config={},
                                secrets={"bot_token": None, "imap_password": None, "smtp_password": None}))
    monkeypatch.setattr(worker, "SessionLocal", lambda: db)
    with pytest.raises(queue.ChannelFailure, match="включён"):
        getattr(worker, runner)()
