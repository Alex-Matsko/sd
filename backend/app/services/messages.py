from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, TicketStatus
from app.models.contact import Contact
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.services import audit, sla


def _resolve_recipient_email(ticket: Ticket) -> str | None:
    contact = ticket.contact
    if contact is None or not contact.emails:
        return None
    primary = next((e.email for e in contact.emails if e.is_primary), None)
    return primary or contact.emails[0].email


def add_message(
    db: Session,
    ticket: Ticket,
    payload: MessageCreate,
    author_user: User | None = None,
    author_contact: Contact | None = None,
) -> Message:
    from app.services.tickets import transition_status

    channel = payload.channel or ticket.channel
    message = Message(
        ticket_id=ticket.id,
        direction=payload.direction,
        channel=channel,
        author_user_id=author_user.id if author_user else None,
        author_contact_id=author_contact.id if author_contact else None,
        body=payload.body,
    )
    db.add(message)
    db.flush()

    # First outbound reply fixes the reaction SLA outcome permanently.
    if payload.direction == MessageDirection.OUTBOUND and ticket.first_response_at is None:
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

    # Engineer replies on an email-channel ticket go out over SMTP (section
    # 2.3: "Ответ уходит в канал обращения"). Deferred import - email_channel
    # imports this module to post the inbound side of the same conversation.
    if payload.direction == MessageDirection.OUTBOUND and channel == Channel.EMAIL:
        from app.services import email_channel

        email_channel.try_send_outbound(db, ticket, message, _resolve_recipient_email(ticket))

    return message
