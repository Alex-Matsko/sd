from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import func, select

from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, TicketStatus
from app.models.contact import Contact
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.services import audit, sla, staff_notifications


def _resolve_recipient_email(ticket: Ticket) -> str | None:
    contact = ticket.contact
    if contact is None or not contact.emails:
        return None
    primary = next((e.email for e in contact.emails if e.is_primary), None)
    return primary or contact.emails[0].email


class RequestConflict(ValueError):
    pass


def add_message(
    db: Session,
    ticket: Ticket,
    payload: MessageCreate,
    author_user: User | None = None,
    author_contact: Contact | None = None,
    attachments: list[tuple[str, bytes, str | None]] | None = None,
) -> Message:
    from app.services.tickets import transition_status

    attachments = attachments or []
    request_key = None
    request_digest = None
    if payload.request_id is not None:
        identity = f"u:{author_user.id}" if author_user else f"c:{author_contact.id}" if author_contact else None
        if identity is None:
            raise ValueError("Не определён автор запроса")
        request_key = f"{identity}:{payload.request_id}"
        request_digest = hashlib.sha256(json.dumps({
            "ticket_id": ticket.id, "payload": payload.model_dump(mode="json", exclude={"request_id"}),
            "files": [(name, hashlib.sha256(content).hexdigest(), mime) for name, content, mime in attachments],
        }, sort_keys=True).encode()).hexdigest()
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(request_key))))
        previous = db.query(Message).filter(Message.request_key == request_key).first()
        if previous is not None:
            if previous.request_digest != request_digest:
                raise RequestConflict("Этот идентификатор запроса уже использован для другого сообщения")
            return previous

    reply_to_message_id = None
    if payload.reply_to_message_id is not None:
        parent = db.get(Message, payload.reply_to_message_id)
        if parent is not None and parent.ticket_id == ticket.id:
            reply_to_message_id = parent.id

    channel = payload.channel or ticket.channel
    message = Message(
        ticket_id=ticket.id,
        direction=payload.direction,
        channel=channel,
        author_user_id=author_user.id if author_user else None,
        author_contact_id=author_contact.id if author_contact else None,
        body=payload.body,
        request_key=request_key,
        request_digest=request_digest,
        reply_to_message_id=reply_to_message_id,
    )
    db.add(message)
    db.flush()

    from app.services import attachments as attachment_service
    from app.services.channel_queue import enqueue_message
    for filename, content, mime in attachments:
        message.attachments.append(attachment_service.store_attachment(message.id, filename, content, mime))
    db.flush()
    external_delivery = payload.direction == MessageDirection.OUTBOUND and channel in (Channel.EMAIL, Channel.MAX, Channel.TELEGRAM)
    if external_delivery:
        job = enqueue_message(db, message)
        job.payload = {**job.payload, "attachment_ids": [item.id for item in message.attachments]}

    # First outbound reply fixes the reaction SLA outcome permanently.
    if payload.direction == MessageDirection.OUTBOUND and not external_delivery and ticket.first_response_at is None:
        sla.register_first_response(ticket, datetime.now(timezone.utc))
        db.add(ticket)

    # Client reply glues the dialog back to work (section 4.2): from
    # "Ожидает клиента" it returns to "В работе"; from "Решена" within the
    # auto-close window it reopens the same way (docs/decisions.md), without
    # recomputing SLA in either case.
    if payload.direction == MessageDirection.INBOUND and TicketStatus(ticket.status) in (
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.RESOLVED,
    ):
        transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    # ТЗ 4.2: ответ клиента «возвращает её в работу И уведомляет исполнителя».
    # Возврат работал, уведомления не было — инженер узнавал об ответе, только
    # если сам открыл заявку.
    #
    # Первое сообщение заявки — это её текст, а не ответ: без этой проверки
    # создание заявки с описанием давало инженеру сразу два уведомления,
    # «новая заявка на вас» и «клиент ответил» про одно и то же (видно только
    # вживую — в тестах заявки заводились без начального сообщения).
    is_first_message = (
        db.query(Message.id).filter(Message.ticket_id == ticket.id, Message.id != message.id).first() is None
    )
    if payload.direction == MessageDirection.INBOUND and not is_first_message:
        staff_notifications.notify_customer_reply(db, ticket)

    audit.record(
        db,
        entity_type="message",
        entity_id=message.id,
        action="created",
        user_id=author_user.id if author_user else None,
        changes={"direction": payload.direction.value, "channel": channel.value},
    )
    db.commit()
    db.refresh(message)

    return message
