"""Shared business rules between the messenger bot channels (MAX, Telegram) -
the parts that must never drift between them: ITSM status labels, the
client-initiated close chain, and the bot's Russian command vocabulary. Wire
format and per-update parsing stay separate per channel (max_channel.py /
telegram_channel.py) - genuinely different enough (MAX's `link` object vs
Telegram's flat `reply_to_message_id`, MAX's opaque `mid` vs Telegram's
per-chat integer `message_id`) that a shared parsing/transport adapter would
cost more than it saves for two channels.
"""

import re

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.core.enums import OPEN_TICKET_STATUSES, TicketStatus
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact, ContactPhone
from app.models.message import Message
from app.models.ticket import Ticket
from app.services import tickets as tickets_service

WELCOME_TEXT = (
    "Здравствуйте! Это бот службы поддержки «Открытые Горизонты». Опишите проблему одним сообщением - "
    "я создам заявку. Команда «Мои заявки» покажет ваши текущие обращения."
)
NEW_TICKET_COMMANDS = {"/new", "новая заявка", "создать заявку", "создать новую"}
MY_TICKETS_COMMANDS = {"/tickets", "мои заявки", "мои обращения"}
# Neither MAX nor Telegram fires a distinct "first contact" event once a user
# has already opened the bot before (verified live for MAX; Telegram sends
# "/start" as a perfectly ordinary text message the same way) - so a
# returning client needs a text command to bring the menu back up too.
START_COMMANDS = {"/start", "start", "старт", "меню", "/menu"}
# Cross-channel identity matching, opt-in (see find_contact_by_phone /
# merge_contacts): the client explicitly asks to link their history from
# another channel, rather than every first contact being gated on a phone
# number (tried and reverted as too much friction for the common case of a
# genuinely new contact - docs/decisions.md).
LINK_PHONE_COMMANDS = {"/link", "связать телефон", "привязать телефон", "объединить обращения"}

STATUS_LABELS_RU = {
    TicketStatus.NEW: "новая",
    TicketStatus.ASSIGNED: "назначена",
    TicketStatus.IN_PROGRESS: "в работе",
    TicketStatus.WAITING_CUSTOMER: "ждём вас",
    TicketStatus.WAITING_THIRD_PARTY: "ждём третью сторону",
    TicketStatus.RESOLVED: "решена",
    TicketStatus.CLOSED: "закрыта",
    TicketStatus.CANCELLED: "отменена",
}

# RESOLVED is deliberately not in OPEN_TICKET_STATUSES (it's not "open" for
# gluing/routing purposes - see messages.add_message's reopen check), but
# it's very much still closeable - in fact the one state CLOSED is directly
# reachable from, so a client-initiated close needs its own, wider set here.
CLOSEABLE_STATUSES = OPEN_TICKET_STATUSES | {TicketStatus.RESOLVED}

PRE_RESOLUTION_STATUSES = (
    TicketStatus.NEW,
    TicketStatus.ASSIGNED,
    TicketStatus.WAITING_CUSTOMER,
    TicketStatus.WAITING_THIRD_PARTY,
)


def normalize_phone_digits(raw: str) -> str:
    """Last 10 digits, ignoring formatting/country-code prefix differences
    (+7/8/7, spaces, dashes, parentheses) - good enough to match "the same
    person" across channels without requiring an exact stored format."""
    digits = re.sub(r"\D", "", raw)
    return digits[-10:] if len(digits) >= 10 else ""


def find_contact_by_phone(db: Session, raw_phone: str) -> Contact | None:
    """Cross-channel identity matching (по запросу заказчика): a client who
    already has a Contact record with a phone on file, messaging via a new
    channel for the first time, gets linked onto that same Contact instead
    of a duplicate with its own separate ticket history. Scans all phones
    rather than a DB-side match - fine at MSP-contact-list scale, and
    normalization has to happen on both sides anyway since the stored
    format isn't guaranteed consistent."""
    normalized = normalize_phone_digits(raw_phone)
    if not normalized:
        return None
    for phone_row in db.query(ContactPhone).all():
        if normalize_phone_digits(phone_row.phone) == normalized:
            return phone_row.contact
    return None


MY_TICKETS_PAGE_SIZE = 5


def my_tickets_page(db: Session, contact: Contact, offset: int = 0) -> tuple[list[Ticket], int]:
    """One page of the client's "Мои заявки" list, plus the total count.

    Ordering happens in SQL - open tickets first, newest first within each
    group - rather than by re-sorting a fetched window. The previous version
    took the 10 newest and only then floated open ones to the top, so a
    still-open ticket older than 10 closed ones dropped off the list
    entirely: exactly the ticket the client most likely wanted."""
    base = db.query(Ticket).filter(Ticket.contact_id == contact.id)
    ordering = case((Ticket.status.in_(OPEN_TICKET_STATUSES), 0), else_=1)
    items = (
        base.order_by(ordering, Ticket.created_at.desc(), Ticket.id.desc())
        .limit(MY_TICKETS_PAGE_SIZE)
        .offset(max(0, offset))
        .all()
    )
    return items, base.count()


def my_tickets_buttons(tickets: list[Ticket], offset: int, total: int) -> list[list[dict]]:
    """Ticket buttons plus a "показать ещё" row when more pages remain. The
    offset travels inside the callback payload, so no extra per-chat state is
    needed to remember where the client is in the list."""
    buttons = [
        [
            {
                "type": "callback",
                "text": f"{t.display_number} — {t.subject[:30]} ({STATUS_LABELS_RU.get(TicketStatus(t.status), t.status)})",
                "payload": f"ticket:{t.id}",
            }
        ]
        for t in tickets
    ]
    next_offset = offset + MY_TICKETS_PAGE_SIZE
    if next_offset < total:
        buttons.append([{"type": "callback", "text": "Показать ещё →", "payload": f"mytickets:{next_offset}"}])
    if offset > 0:
        previous = max(0, offset - MY_TICKETS_PAGE_SIZE)
        buttons.append([{"type": "callback", "text": "← Назад", "payload": f"mytickets:{previous}"}])
    return buttons


def my_tickets_caption(tickets: list[Ticket], offset: int, total: int) -> str:
    if not tickets:
        return "У вас пока нет заявок."
    shown_from = offset + 1
    shown_to = offset + len(tickets)
    open_count = sum(1 for t in tickets if TicketStatus(t.status) in OPEN_TICKET_STATUSES)
    if total <= MY_TICKETS_PAGE_SIZE:
        return f"Ваши заявки (открытых: {open_count} из {total}):"
    return f"Ваши заявки {shown_from}–{shown_to} из {total} (сначала открытые):"


def merge_contacts(db: Session, from_contact: Contact, into_contact: Contact) -> None:
    """Combines two Contact records that turned out to be the same person -
    typically one auto-created per messenger channel before a shared phone
    number linked them (find_contact_by_phone), or a dispatcher merging two
    contacts they recognized as duplicates by hand. Moves tickets, messages,
    and channel-conversation-state pointers onto `into_contact`, then removes
    the now-empty `from_contact`. Channel ids only copy over where the
    target doesn't already have one, so an existing linked identity is never
    clobbered; phone/email rows are moved unless the target already has that
    exact value (both columns are globally unique, so a literal duplicate
    would otherwise violate the constraint mid-merge)."""
    db.query(Ticket).filter(Ticket.contact_id == from_contact.id).update({"contact_id": into_contact.id})
    db.query(Message).filter(Message.author_contact_id == from_contact.id).update({"author_contact_id": into_contact.id})
    db.query(ChannelConversationState).filter(ChannelConversationState.contact_id == from_contact.id).update(
        {"contact_id": into_contact.id}
    )

    from_max_id, from_telegram_id = from_contact.max_id, from_contact.telegram_id
    from_contact.max_id = None
    from_contact.telegram_id = None
    db.flush()
    if into_contact.max_id is None and from_max_id is not None:
        into_contact.max_id = from_max_id
    if into_contact.telegram_id is None and from_telegram_id is not None:
        into_contact.telegram_id = from_telegram_id

    # Contact.phones/emails cascade "all, delete-orphan": reassigning just
    # the raw contact_id column isn't enough, since the ORM tracks orphan
    # status by relationship-collection membership, not the FK value alone -
    # from_contact.delete() below would cascade-delete a phone/email row
    # that still looked like "its child" in the session's eyes even after
    # its contact_id had been updated. Removing/appending via the
    # collections themselves keeps that bookkeeping consistent.
    existing_phones = {p.phone for p in into_contact.phones}
    for phone in list(from_contact.phones):
        from_contact.phones.remove(phone)
        if phone.phone in existing_phones:
            db.delete(phone)
        else:
            into_contact.phones.append(phone)

    existing_emails = {e.email for e in into_contact.emails}
    for email in list(from_contact.emails):
        from_contact.emails.remove(email)
        if email.email in existing_emails:
            db.delete(email)
        else:
            into_contact.emails.append(email)

    db.add(into_contact)
    db.flush()
    db.delete(from_contact)
    db.commit()


def close_ticket_chain(db: Session, ticket: Ticket) -> Ticket:
    """Client-initiated close ("Закрыть заявку", по запросу заказчика).
    CLOSED is reachable only from RESOLVED (ALLOWED_TRANSITIONS), so this
    chains the same one-hop transitions transition_status already validates
    - IN_PROGRESS -> RESOLVED -> CLOSED, hopping through IN_PROGRESS first
    if needed - rather than a special-cased jump that would bypass SLA/audit
    bookkeeping. Accepted trade-off: the client sees each hop's own status
    notification plus the CSAT request, not one single message."""
    status = TicketStatus(ticket.status)
    if status in PRE_RESOLUTION_STATUSES:
        ticket = tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
        status = TicketStatus.IN_PROGRESS
    if status == TicketStatus.IN_PROGRESS:
        ticket = tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    if TicketStatus(ticket.status) == TicketStatus.RESOLVED:
        ticket = tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)
    return ticket
