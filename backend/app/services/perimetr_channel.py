"""Канал «Периметр»: окно «Поддержка» в продуктах «Периметр» (по запросу
заказчика, вне исходного ТЗ).

Клиент пишет в окне продукта — на сервере VMS или в кабинете облака.
Служба продукта (облако или издатель для серверов VMS) передаёт сообщение
сюда, и дальше это обычная заявка: очередь, SLA, маршрутизация, ответ
инженера в карточке. Отправлять ответ некуда — у продукта нет ни бота, ни
почты, — поэтому продукт сам забирает переписку: list_messages.

Переписку определяет ключ, который задаёт служба продукта. Внутренние
заметки наружу не уходят: сводка о сервере, которую клиент приложил,
ложится заметкой и видна только сотрудникам.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.enums import (
    OPEN_TICKET_STATUSES,
    Channel,
    ImpactUrgencyLevel,
    MessageDirection,
    TicketStatus,
    TicketType,
)
from app.models.contact import Contact, ContactEmail
from app.models.message import Message
from app.models.perimetr_conversation import PerimetrConversation, PerimetrConversationTicket
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import messages as messages_service
from app.services import tickets as tickets_service
from app.services.messenger_common import STATUS_LABELS_RU
from app.services.unknown_queue import get_or_create_unknown_organization

TOPICS = {
    "camera": "Не подключается камера",
    "recording": "Запись и архив",
    "license": "Лицензия",
    "update": "Обновление",
    "billing": "Оплата и тариф",
    "other": "Другое",
}

# Заявка, решённая, но не закрытая, ещё принимает ответ клиента: add_message
# вернёт её в работу. Закрытая и отменённая — нет, следующее сообщение
# откроет новую.
GLUE_STATUSES = OPEN_TICKET_STATUSES | {TicketStatus.RESOLVED}


@dataclass
class Inbound:
    key: str
    product: str
    text: str
    topic: str = "other"
    # Кто пишет: имя, организация или заказчик по лицензии, контакт для ответа.
    name: str = ""
    customer: str = ""
    email: str = ""
    phone: str = ""
    # Почту подтвердила служба продукта (облако — письмом при регистрации).
    # Только тогда переписка привязывается к существующему контакту с этим
    # адресом: на сервере VMS адрес вписывают от руки, и чужой адрес
    # открыл бы чужие заявки.
    email_verified: bool = False
    # Кто на стороне продукта: версия, отпечаток, адрес сервера — в заметку
    # при открытии заявки.
    server: str = ""
    # Сводка о сервере или кабинете, если клиент её приложил, — заметкой.
    report: str = ""


def _contact_for(db: Session, msg: Inbound) -> Contact:
    if msg.email and msg.email_verified:
        row = db.query(ContactEmail).filter(ContactEmail.email == msg.email.lower()).first()
        if row is not None:
            return row.contact
    organization = get_or_create_unknown_organization(db)
    title = msg.customer or msg.name or msg.product
    contact = Contact(organization_id=organization.id, full_name=f"{msg.product}: {title}"[:255], is_confirmed=False)
    db.add(contact)
    db.flush()
    if msg.email and msg.email_verified:
        contact.emails.append(ContactEmail(email=msg.email.lower(), is_primary=True))
        db.flush()
    return contact


def _conversation(db: Session, msg: Inbound) -> PerimetrConversation:
    conv = db.query(PerimetrConversation).filter(PerimetrConversation.key == msg.key).with_for_update().first()
    if conv is None:
        conv = PerimetrConversation(key=msg.key, product=msg.product[:64], contact_id=_contact_for(db, msg).id)
        db.add(conv)
        db.flush()
    return conv


def _who(msg: Inbound) -> str:
    parts = [p for p in (msg.name, msg.customer, msg.email, msg.phone) if p]
    return " · ".join(parts)


def post_message(db: Session, msg: Inbound) -> Ticket:
    """Сообщение клиента: в открытую заявку переписки или новой заявкой."""
    conv = _conversation(db, msg)
    ticket = db.get(Ticket, conv.active_ticket_id) if conv.active_ticket_id else None
    created = False
    if ticket is not None and TicketStatus(ticket.status) in GLUE_STATUSES:
        messages_service.add_message(
            db,
            ticket,
            MessageCreate(direction=MessageDirection.INBOUND, body=msg.text, channel=Channel.PERIMETR),
            author_contact=db.get(Contact, conv.contact_id),
        )
    else:
        topic = TOPICS.get(msg.topic, TOPICS["other"])
        first_line = msg.text.strip().splitlines()[0] if msg.text.strip() else ""
        ticket = tickets_service.create_ticket(
            db,
            TicketCreate(
                contact_id=conv.contact_id,
                type=TicketType.INCIDENT,
                channel=Channel.PERIMETR,
                subject=f"{msg.product} · {topic}: {first_line}"[:500],
                impact=ImpactUrgencyLevel.MEDIUM,
                urgency=ImpactUrgencyLevel.MEDIUM,
                initial_message=msg.text,
            ),
            actor=None,
        )
        created = True
        conv.active_ticket_id = ticket.id
        db.add(PerimetrConversationTicket(conversation_id=conv.id, ticket_id=ticket.id))
        db.add(conv)
        db.commit()
    # Заметка — только с новыми сведениями: при открытии заявки и когда
    # клиент приложил сводку. На каждое сообщение она засоряла бы переписку.
    if created or msg.report:
        note = f"Из окна «Поддержка» {msg.product}. Контакт для ответа: {_who(msg) or 'не указан'}."
        if msg.server:
            note += "\n" + msg.server
        if msg.report:
            note += "\n\n" + msg.report
        messages_service.add_message(
            db, ticket, MessageCreate(direction=MessageDirection.INTERNAL_NOTE, body=note, channel=Channel.PERIMETR)
        )
    db.refresh(ticket)
    return ticket


def list_messages(db: Session, key: str, after_id: int = 0) -> dict | None:
    """Переписка для окна продукта: сообщения клиента и ответы сотрудников,
    без внутренних заметок, и заявки с их статусом."""
    conv = db.query(PerimetrConversation).filter(PerimetrConversation.key == key).first()
    if conv is None:
        return None
    ticket_ids = [
        row.ticket_id
        for row in db.query(PerimetrConversationTicket).filter(PerimetrConversationTicket.conversation_id == conv.id)
    ]
    tickets = db.query(Ticket).filter(Ticket.id.in_(ticket_ids)).order_by(Ticket.id).all() if ticket_ids else []
    rows = (
        db.query(Message, User.full_name)
        .outerjoin(User, User.id == Message.author_user_id)
        .filter(
            Message.ticket_id.in_(ticket_ids or [0]),
            Message.id > after_id,
            Message.direction.in_([MessageDirection.INBOUND, MessageDirection.OUTBOUND]),
        )
        .order_by(Message.id)
        .limit(500)
        .all()
    )
    numbers = {t.id: t.display_number for t in tickets}
    return {
        "tickets": [
            {
                "number": t.display_number,
                "subject": t.subject,
                "status": STATUS_LABELS_RU.get(TicketStatus(t.status), str(t.status)),
                "open": TicketStatus(t.status) in GLUE_STATUSES,
            }
            for t in tickets
        ],
        "messages": [
            {
                "id": m.id,
                "ticket": numbers.get(m.ticket_id, ""),
                "from": "client" if m.direction == MessageDirection.INBOUND else "support",
                "author": (name or "Поддержка") if m.direction == MessageDirection.OUTBOUND else "",
                "text": m.body,
                "at": m.created_at.isoformat(),
            }
            for m, name in rows
        ],
    }


# --- Обращения: несколько заявок с историей ----------------------------------
#
# Окно продукта показывает обращения списком, у каждого — статус, исполнитель,
# группа и лента: сообщения и события из журнала (взята в работу, назначен
# исполнитель, решена, закрыта). Новое обращение — всегда новая заявка;
# ответ уходит в выбранную. Видно только то, что относится к переписке
# (ключ продукта), внутренние заметки — никогда.

CLIENT_STATUS = {
    TicketStatus.NEW: "Новая",
    TicketStatus.ASSIGNED: "Назначена",
    TicketStatus.IN_PROGRESS: "В работе",
    TicketStatus.WAITING_CUSTOMER: "Ждём вашего ответа",
    TicketStatus.WAITING_THIRD_PARTY: "Ждём ответа третьей стороны",
    TicketStatus.RESOLVED: "Решена",
    TicketStatus.CLOSED: "Закрыта",
    TicketStatus.CANCELLED: "Отменена",
}

# Закрытая и отменённая заявка ответов не принимает: вопрос задают новым
# обращением (CLOSED в ALLOWED_TRANSITIONS конечен).
FINAL_STATUSES = {TicketStatus.CLOSED, TicketStatus.CANCELLED}


class TicketGone(Exception):
    """Заявки нет в этой переписке — для продукта это «не найдено»."""


class TicketFinal(Exception):
    """Заявка закрыта или отменена."""


def _organization_for(db: Session, customer: str):
    """Юрлицо из кабинета продукта: заказчик по лицензии у VMS, организация
    у облака. Ищется по названию и по юридическому названию; если такой
    организации ещё нет — заводится, чтобы обращение сразу легло к своему
    клиенту, а не в «Неизвестные»."""
    from sqlalchemy import func as sa_func

    from app.models.organization import Organization

    name = customer.strip()
    if not name:
        return get_or_create_unknown_organization(db)
    lowered = name.lower()
    org = (
        db.query(Organization)
        .filter((sa_func.lower(Organization.name) == lowered) | (sa_func.lower(Organization.legal_name) == lowered))
        .first()
    )
    if org is None:
        org = Organization(name=name[:255], legal_name=name[:255])
        db.add(org)
        db.flush()
    return org


def _contact_v2(db: Session, msg: Inbound) -> Contact:
    """Контакт по почте учётной записи продукта. Существующий контакт с этой
    почтой берётся, если почту подтвердил продукт или он из той же
    организации; иначе заводится новый. Читать переписку это не даёт: ответы
    отдаются только по ключу продукта."""
    organization = _organization_for(db, msg.customer)
    email = msg.email.strip().lower()
    if email:
        row = db.query(ContactEmail).filter(ContactEmail.email == email).first()
        if row is not None and (msg.email_verified or row.contact.organization_id == organization.id):
            return row.contact
        if row is None:
            contact = Contact(organization_id=organization.id, full_name=(msg.name or email)[:255], is_confirmed=msg.email_verified)
            db.add(contact)
            db.flush()
            contact.emails.append(ContactEmail(email=email, is_primary=True))
            db.flush()
            return contact
    title = msg.name or msg.customer or msg.product
    contact = (
        db.query(Contact)
        .filter(Contact.organization_id == organization.id, Contact.full_name == f"{msg.product}: {title}"[:255])
        .first()
    )
    if contact is None:
        contact = Contact(organization_id=organization.id, full_name=f"{msg.product}: {title}"[:255], is_confirmed=False)
        db.add(contact)
        db.flush()
    return contact


def _conversation_v2(db: Session, msg: Inbound, contact: Contact) -> PerimetrConversation:
    conv = db.query(PerimetrConversation).filter(PerimetrConversation.key == msg.key).with_for_update().first()
    if conv is None:
        conv = PerimetrConversation(key=msg.key, product=msg.product[:64], contact_id=contact.id)
        db.add(conv)
        db.flush()
    return conv


def _ticket_of(db: Session, key: str, number: int) -> Ticket:
    conv = db.query(PerimetrConversation).filter(PerimetrConversation.key == key).first()
    if conv is None:
        raise TicketGone()
    ticket = (
        db.query(Ticket)
        .join(PerimetrConversationTicket, PerimetrConversationTicket.ticket_id == Ticket.id)
        .filter(PerimetrConversationTicket.conversation_id == conv.id, Ticket.number == number)
        .first()
    )
    if ticket is None:
        raise TicketGone()
    return ticket


def create_ticket(db: Session, msg: Inbound, subject: str = "") -> Ticket:
    """Новое обращение — всегда новая заявка."""
    contact = _contact_v2(db, msg)
    conv = _conversation_v2(db, msg, contact)
    topic = TOPICS.get(msg.topic, TOPICS["other"])
    first_line = (subject or (msg.text.strip().splitlines() or [""])[0]).strip()
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id,
            type=TicketType.INCIDENT,
            channel=Channel.PERIMETR,
            subject=f"{topic}: {first_line}"[:500] if first_line else topic,
            impact=ImpactUrgencyLevel.MEDIUM,
            urgency=ImpactUrgencyLevel.MEDIUM,
            initial_message=msg.text,
        ),
        actor=None,
    )
    db.add(PerimetrConversationTicket(conversation_id=conv.id, ticket_id=ticket.id))
    conv.active_ticket_id = ticket.id
    db.add(conv)
    db.commit()
    note = f"Обращение из {msg.product}. Контакт: {_who(msg) or 'не указан'}."
    if msg.server:
        note += "\n" + msg.server
    if msg.report:
        note += "\n\n" + msg.report
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INTERNAL_NOTE, body=note, channel=Channel.PERIMETR)
    )
    db.refresh(ticket)
    return ticket


def reply(db: Session, key: str, number: int, text: str) -> Ticket:
    ticket = _ticket_of(db, key, number)
    if TicketStatus(ticket.status) in FINAL_STATUSES:
        raise TicketFinal()
    messages_service.add_message(
        db,
        ticket,
        MessageCreate(direction=MessageDirection.INBOUND, body=text, channel=Channel.PERIMETR),
        author_contact=db.get(Contact, ticket.contact_id),
    )
    db.refresh(ticket)
    return ticket


def close_by_client(db: Session, key: str, number: int) -> Ticket:
    """«Вопрос решён» из окна продукта — та же цепочка, что у мессенджеров."""
    from app.services.messenger_common import close_ticket_chain

    ticket = _ticket_of(db, key, number)
    if TicketStatus(ticket.status) in FINAL_STATUSES:
        return ticket
    return close_ticket_chain(db, ticket)


def _summary(db: Session, ticket: Ticket) -> dict:
    from app.models.team import Team

    status = TicketStatus(ticket.status)
    engineer = db.get(User, ticket.assigned_engineer_id) if ticket.assigned_engineer_id else None
    team = db.get(Team, ticket.team_id) if ticket.team_id else None
    visible = [MessageDirection.INBOUND, MessageDirection.OUTBOUND]
    last = (
        db.query(Message)
        .filter(Message.ticket_id == ticket.id, Message.direction.in_(visible))
        .order_by(Message.id.desc())
        .first()
    )
    last_support = (
        db.query(Message.id)
        .filter(Message.ticket_id == ticket.id, Message.direction == MessageDirection.OUTBOUND)
        .order_by(Message.id.desc())
        .first()
    )
    return {
        "number": ticket.number,
        "display": ticket.display_number,
        "subject": ticket.subject,
        "status": status.value,
        "status_label": CLIENT_STATUS.get(status, status.value),
        "final": status in FINAL_STATUSES,
        "assignee": engineer.full_name if engineer else "",
        "team": getattr(team, "name", "") if team else "",
        "created_at": ticket.created_at.isoformat(),
        "updated_at": (last.created_at if last and last.created_at > ticket.updated_at else ticket.updated_at).isoformat(),
        "last_message": (
            {"from": "client" if last.direction == MessageDirection.INBOUND else "support", "text": last.body[:200], "at": last.created_at.isoformat()}
            if last
            else None
        ),
        "last_support_id": last_support[0] if last_support else 0,
    }


def list_tickets(db: Session, key: str) -> list[dict]:
    conv = db.query(PerimetrConversation).filter(PerimetrConversation.key == key).first()
    if conv is None:
        return []
    tickets = (
        db.query(Ticket)
        .join(PerimetrConversationTicket, PerimetrConversationTicket.ticket_id == Ticket.id)
        .filter(PerimetrConversationTicket.conversation_id == conv.id)
        .all()
    )
    rows = [_summary(db, t) for t in tickets]
    # Сначала открытые, внутри — по последнему движению.
    open_rows = sorted([r for r in rows if not r["final"]], key=lambda r: r["updated_at"], reverse=True)
    done_rows = sorted([r for r in rows if r["final"]], key=lambda r: r["updated_at"], reverse=True)
    return open_rows + done_rows


def ticket_detail(db: Session, key: str, number: int) -> dict:
    """Карточка обращения: сводка и лента — сообщения и события журнала."""
    from app.models.audit import AuditLog
    from app.models.team import Team

    ticket = _ticket_of(db, key, number)
    events: list[dict] = []
    for m, name in (
        db.query(Message, User.full_name)
        .outerjoin(User, User.id == Message.author_user_id)
        .filter(Message.ticket_id == ticket.id, Message.direction.in_([MessageDirection.INBOUND, MessageDirection.OUTBOUND]))
        .order_by(Message.id)
    ):
        events.append(
            {
                "id": f"m{m.id}",
                "kind": "message",
                "from": "client" if m.direction == MessageDirection.INBOUND else "support",
                "author": (name or "Поддержка") if m.direction == MessageDirection.OUTBOUND else "",
                "text": m.body,
                "at": m.created_at.isoformat(),
            }
        )
    users: dict[int, str] = {}

    def user_name(uid):
        if not uid:
            return ""
        if uid not in users:
            u = db.get(User, uid)
            users[uid] = u.full_name if u else ""
        return users[uid]

    for a in (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket.id)
        .order_by(AuditLog.id)
    ):
        changes = a.changes or {}
        text = ""
        if a.action == "created":
            text = "Обращение зарегистрировано"
        elif a.action == "status_changed":
            try:
                text = "Статус: " + CLIENT_STATUS[TicketStatus(changes.get("to"))]
            except (KeyError, ValueError):
                continue
        elif a.action == "updated" and "assigned_engineer_id" in changes:
            to = changes["assigned_engineer_id"].get("to")
            text = f"Исполнитель: {user_name(to)}" if to else "Исполнитель снят"
        elif a.action == "updated" and "team_id" in changes:
            to = changes["team_id"].get("to")
            team = db.get(Team, to) if to else None
            text = f"Передана группе: {team.name}" if team else ""
        if text:
            events.append({"id": f"a{a.id}", "kind": "event", "from": "system", "author": user_name(a.user_id), "text": text, "at": a.created_at.isoformat()})
    events.sort(key=lambda e: (e["at"], e["id"]))
    return {**_summary(db, ticket), "events": events}
