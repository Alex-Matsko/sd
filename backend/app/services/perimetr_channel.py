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
