"""Shared business rules between the messenger bot channels (MAX, Telegram) -
the parts that must never drift between them: ITSM status labels, safe
contact-link requests, and the bot's Russian command vocabulary. Wire
format and per-update parsing stay separate per channel (max_channel.py /
telegram_channel.py) - genuinely different enough (MAX's `link` object vs
Telegram's flat `reply_to_message_id`, MAX's opaque `mid` vs Telegram's
per-chat integer `message_id`) that a shared parsing/transport adapter would
cost more than it saves for two channels.
"""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.enums import OPEN_TICKET_STATUSES, TicketStatus
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact, ContactPhone
from app.models.message import Message
from app.models.ticket import Ticket
from app.services import tickets as tickets_service
from app.services.ticket_messages import STATUS_LABELS_RU, ticket_notice

WELCOME_TEXT = (
    "Здравствуйте! Это служба поддержки «Открытые Горизонты». "
    "Чтобы продолжить переписку, нажмите «Ответить по этой заявке» под сообщением или выберите обращение в «Мои заявки». "
    "Для нового вопроса нажмите «Создать новую». "
    "Помощь: /help. Отменить текущий ввод: /cancel."
)

NEW_TICKET_COMMANDS = {"/new", "новая заявка", "создать заявку", "создать новую"}
MY_TICKETS_COMMANDS = {"/tickets", "мои заявки", "мои обращения"}
# Neither MAX nor Telegram fires a distinct "first contact" event once a user
# has already opened the bot before (verified live for MAX; Telegram sends
# "/start" as a perfectly ordinary text message the same way) - so a
# returning client needs a text command to bring the menu back up too.
START_COMMANDS = {"/start", "start", "старт", "меню", "/menu"}
# A client may request linking; only staff can confirm identity and merge.
LINK_PHONE_COMMANDS = {"/link", "связать телефон", "привязать телефон", "объединить обращения"}


def request_contact_link(db, channel, state, contact):
    """A typed phone number proves no identity. Only staff may merge contacts,
    after confirming through an already trusted customer channel."""
    from app.core.enums import NotificationType, UserRole
    from app.models.audit import AuditLog
    from app.models.notification import Notification
    from app.models.user import User
    from app.services import audit, realtime

    state.awaiting_phone_confirmation = False
    db.add(state)
    recent = db.query(AuditLog.id).filter(
        AuditLog.entity_type == "contact", AuditLog.entity_id == contact.id,
        AuditLog.action == "contact_link_requested",
        AuditLog.created_at >= datetime.now(timezone.utc) - timedelta(minutes=15),
    ).first()
    if recent is None:
        audit.record(db, entity_type="contact", entity_id=contact.id, action="contact_link_requested",
                     user_id=None, changes={"channel": channel})
        title = f"Контакт #{contact.id} — {contact.full_name}: запрос объединения каналов ({channel}). Подтвердите личность через прежний канал перед объединением в «Контактах»."[:500]
        for user_id, in db.query(User.id).filter(User.is_active.is_(True), User.role.in_([UserRole.DISPATCHER, UserRole.MANAGER, UserRole.ADMIN])):
            db.add(Notification(user_id=user_id, type=NotificationType.CONTACT_LINK_REQUEST, title=title))
            realtime.publish_notification(db, user_id, NotificationType.CONTACT_LINK_REQUEST.value, title, None)
    db.commit()
    return "Запрос на объединение обращений передан сотруднику поддержки. Он подтвердит привязку через ваш прежний канал связи. До подтверждения история других контактов недоступна. Вы можете продолжать писать в этот чат."



def normalize_phone_digits(raw: str) -> str:
    """Last 10 digits, ignoring formatting/country-code prefix differences
    (+7/8/7, spaces, dashes, parentheses) - good enough to match "the same
    person" across channels without requiring an exact stored format."""
    digits = re.sub(r"\D", "", raw)
    return digits[-10:] if len(digits) >= 10 else ""


def find_contact_by_phone(db: Session, raw_phone: str) -> Contact | None:
    """Directory lookup only. A match is never proof of identity and must
    not authorize a messenger link or a merge of customer histories."""
    normalized = normalize_phone_digits(raw_phone)
    if not normalized:
        return None
    for phone_row in db.query(ContactPhone).all():
        if normalize_phone_digits(phone_row.phone) == normalized:
            return phone_row.contact
    return None


# Full subjects live in the message, not in provider-truncated button labels.
# Three 500-character subjects also fit when every character needs two UTF-16 units.
MY_TICKETS_PAGE_SIZE = 3
TICKET_SCOPES = {
    'active': ("Активные", OPEN_TICKET_STATUSES),
    'acceptance': ("На приёмке", {TicketStatus.RESOLVED}),
    'completed': ("Завершённые", {TicketStatus.CLOSED, TicketStatus.CANCELLED}),
}
STAGE_DETAILS = {
    TicketStatus.NEW: 'Ещё не взята в работу.',
    TicketStatus.ASSIGNED: 'Исполнитель назначен, работа ещё не началась.',
    TicketStatus.IN_PROGRESS: 'Исполнитель выполняет задачу.',
    TicketStatus.WAITING_CUSTOMER: 'Работа приостановлена: нужен ваш ответ.',
    TicketStatus.WAITING_THIRD_PARTY: 'Ожидаем подрядчика или поставщика.',
    TicketStatus.RESOLVED: 'Работы завершены: проверьте и примите результат.',
    TicketStatus.CLOSED: 'Заявка закрыта.',
    TicketStatus.CANCELLED: 'Выполнение отменено.',
}


def ticket_stage(ticket):
    status = TicketStatus(ticket.status)
    if status == TicketStatus.RESOLVED and not ticket.resolution_message_id:
        return 'Отмечена решённой, но результат ещё не опубликован сотрудником.'
    if status == TicketStatus.CLOSED and ticket.accepted_at:
        return 'Результат принят, заявка закрыта.'
    return STAGE_DETAILS[status]


def my_tickets_counts(db: Session, contact: Contact) -> dict[str, int]:
    rows = dict(db.query(Ticket.status, func.count(Ticket.id)).filter(Ticket.contact_id == contact.id).group_by(Ticket.status).all())
    result = {scope: sum(rows.get(status, 0) for status in statuses) for scope, (_, statuses) in TICKET_SCOPES.items()}
    result['working'] = rows.get(TicketStatus.IN_PROGRESS, 0)
    return result


def my_tickets_page(db: Session, contact: Contact, offset: int = 0, scope: str = 'active') -> tuple[list[Ticket], int]:
    statuses = TICKET_SCOPES[scope][1]
    base = db.query(Ticket).filter(Ticket.contact_id == contact.id, Ticket.status.in_(statuses))
    ordering = case((Ticket.status == TicketStatus.IN_PROGRESS, 0), else_=1)
    items = base.order_by(ordering, Ticket.updated_at.desc(), Ticket.id.desc()).limit(MY_TICKETS_PAGE_SIZE).offset(max(0, offset)).all()
    return items, base.count()


def my_tickets_buttons(tickets: list[Ticket], offset: int, total: int, scope: str = 'active', counts=None) -> list[list[dict]]:
    counts = counts or {scope: total}
    result = [[{'type': 'callback', 'text': f'Открыть {t.display_number} · {STATUS_LABELS_RU[TicketStatus(t.status)]}',
                'payload': f'ticket:{t.id}'}] for t in tickets]
    navigation = []
    if offset > 0:
        navigation.append({'type': 'callback', 'text': '← Назад', 'payload': f'mytickets:{scope}:{max(0, offset - MY_TICKETS_PAGE_SIZE)}'})
    if offset + len(tickets) < total:
        navigation.append({'type': 'callback', 'text': 'Далее →', 'payload': f'mytickets:{scope}:{offset + len(tickets)}'})
    if navigation:
        result.append(navigation)
    for key, (label, _) in TICKET_SCOPES.items():
        result.append([{'type': 'callback', 'text': f'{"• " if key == scope else ""}{label} ({counts.get(key, 0)})', 'payload': f'mytickets:{key}:0'}])
    result.append([{'type': 'callback', 'text': 'Создать новую заявку', 'payload': 'cmd:new_ticket'}])
    result.append([{'type': 'callback', 'text': 'Как пользоваться поддержкой', 'payload': 'cmd:help'}])
    return result


def my_tickets_caption(tickets: list[Ticket], offset: int, total: int, scope: str = 'active', counts=None) -> str:
    counts = counts or {scope: total}
    lines = ['Мои заявки · ' + TICKET_SCOPES[scope][0],
             f'Активные: {counts.get("active", 0)} · На приёмке: {counts.get("acceptance", 0)} · Завершённые: {counts.get("completed", 0)}']
    if 'working' in counts:
        lines.append(f'Сейчас в работе: {counts["working"]}.')
    if not tickets:
        lines.append({'active': 'Активных заявок нет.', 'acceptance': 'Нет заявок, ожидающих вашей приёмки.', 'completed': 'Завершённых заявок пока нет.'}[scope])
    for ticket in tickets:
        status = TicketStatus(ticket.status)
        lines.extend(['', f'{ticket.display_number} — {ticket.subject}',
                      f'Статус: {STATUS_LABELS_RU[status]}. {ticket_stage(ticket)}'])
        plan = planning_summary(ticket)
        if plan:
            lines.append(plan.strip())
        if status in OPEN_TICKET_STATUSES:
            if ticket.planned_due_at is None:
                lines.append('Плановый срок решения: ещё не указан.')
            if ticket.estimated_minutes is None:
                lines.append('Оценка трудозатрат: ещё не указана.')
    if tickets:
        lines.extend(['', f'Показаны {offset + 1}–{offset + len(tickets)} из {total}.', 'Нажмите номер ниже — откроется карточка с описанием заявки.'])
    lines.append('Закрытые и отменённые доступны в «Завершённые». Готовые работы ждут вас в «На приёмке».')
    return '\n'.join(lines)


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
    # Переписка из окна «Периметр» держит контакт так же, как состояние бота.
    from app.models.perimetr_conversation import PerimetrConversation

    db.query(PerimetrConversation).filter(PerimetrConversation.contact_id == from_contact.id).update(
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

    from app.models.messenger_reply import MessengerReply
    db.query(MessengerReply).filter(MessengerReply.contact_id == from_contact.id).update(
        {MessengerReply.contact_id: into_contact.id}, synchronize_session='fetch')
    db.add(into_contact)
    db.flush()
    db.delete(from_contact)
    db.commit()


def close_ticket_chain(db: Session, ticket: Ticket) -> Ticket:
    """Compatibility entry point: closing requires an explicitly accepted result.
    Never manufacture work/resolution transitions for a client's old button."""
    if ticket.status != TicketStatus.RESOLVED or not ticket.resolution_message_id or not ticket.accepted_at:
        raise ValueError("Сначала клиент должен принять опубликованный результат")
    return tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)


def planning_summary(ticket: Ticket) -> str:
    lines = []
    if ticket.planned_due_at is not None:
        due = ticket.planned_due_at.astimezone(timezone.utc)
        lines.append("Плановый срок решения: " + due.strftime("%d.%m.%Y %H:%M UTC"))
    if ticket.estimated_minutes is not None:
        hours, minutes = divmod(ticket.estimated_minutes, 60)
        effort = f"{hours} ч" + (f" {minutes} мин" if minutes else "") if hours else f"{minutes} мин"
        lines.append("Оценка трудозатрат: " + effort)
    return "\n\n" + "\n".join(lines) if lines else ""
