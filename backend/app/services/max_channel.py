"""MAX messenger channel (section 2.2: "Аналогично Telegram") - client-side
identification, dialog gluing, "Мои заявки", explicit new-ticket creation, and
post-closure CSAT (section 2.1's bot feature list, mirrored for MAX).

Update/Message JSON shapes are transcribed from the public MAX Bot API docs
(dev.max.ru/docs-api) as of 2026-07-22 - the customer's own prior MAX bridge
was never finished and unavailable as a reference, and no live bot token was
available during development to verify shapes against a real server. All
inbound parsing is isolated in `_extract_incoming` so a field-name correction,
once verified against a real bot, is a one-function fix - see
docs/decisions.md, "Технические примечания по Этапу 5".
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.core.enums import (
    Channel,
    MessageDirection,
    OPEN_TICKET_STATUSES,
    Priority,
    TicketStatus,
    TicketType,
)
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact
from app.models.message import Message
from app.models.ticket import Ticket
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import attachments as attachments_service
from app.services import integration_settings
from app.services import max_client
from app.services import messages as messages_service
from app.services import tickets as tickets_service
from app.services.unknown_queue import get_or_create_unknown_organization

logger = logging.getLogger("app.max_channel")

WELCOME_TEXT = (
    "Здравствуйте! Это бот службы поддержки «Открытые Горизонты». Опишите проблему одним сообщением - "
    "я создам заявку. Команда «Мои заявки» покажет ваши текущие обращения."
)
NEW_TICKET_COMMANDS = {"/new", "новая заявка", "создать заявку", "создать новую"}
MY_TICKETS_COMMANDS = {"/tickets", "мои заявки", "мои обращения"}

_STATUS_LABELS_RU = {
    TicketStatus.NEW: "новая",
    TicketStatus.ASSIGNED: "назначена",
    TicketStatus.IN_PROGRESS: "в работе",
    TicketStatus.WAITING_CUSTOMER: "ждём вас",
    TicketStatus.WAITING_THIRD_PARTY: "ждём третью сторону",
    TicketStatus.RESOLVED: "решена",
    TicketStatus.CLOSED: "закрыта",
    TicketStatus.CANCELLED: "отменена",
}


@dataclass
class MaxConfig:
    token: str
    base_url: str
    poll_timeout_seconds: int


@dataclass
class ParsedUpdate:
    kind: str  # "text" | "callback" | "bot_started"
    external_user_id: str
    chat_id: str
    display_name: str
    text: str = ""
    callback_payload: str = ""
    attachments: list[dict] = field(default_factory=list)


def load_max_config(db: Session) -> MaxConfig | None:
    setting = integration_settings.get(db, Channel.MAX)
    if setting is None or not setting.is_enabled:
        return None
    token = integration_settings.decrypt_secret(setting, "bot_token")
    if not token:
        return None
    cfg = setting.config or {}
    return MaxConfig(
        token=token,
        base_url=cfg.get("base_url") or max_client.DEFAULT_BASE_URL,
        poll_timeout_seconds=int(cfg.get("poll_timeout_seconds") or 20),
    )


def get_marker(db: Session) -> int | None:
    setting = integration_settings.get(db, Channel.MAX)
    if setting is None:
        return None
    return (setting.config or {}).get("_marker")


def save_marker(db: Session, marker: int | None) -> None:
    if marker is None:
        return
    setting = integration_settings.get_or_create(db, Channel.MAX)
    cfg = dict(setting.config or {})
    cfg["_marker"] = marker
    setting.config = cfg
    db.add(setting)
    db.commit()


def _extract_incoming(update: dict) -> ParsedUpdate | None:
    update_type = update.get("update_type")

    if update_type == "message_created":
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        body = message.get("body") or {}
        user_id = sender.get("user_id")
        chat_id = recipient.get("chat_id")
        if user_id is None or chat_id is None:
            return None
        return ParsedUpdate(
            kind="text",
            external_user_id=str(user_id),
            chat_id=str(chat_id),
            display_name=sender.get("name") or sender.get("username") or "",
            text=(body.get("text") or "").strip(),
            attachments=body.get("attachments") or [],
        )

    if update_type == "message_callback":
        callback = update.get("callback") or {}
        user = callback.get("user") or {}
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        user_id = user.get("user_id")
        chat_id = recipient.get("chat_id") or callback.get("chat_id")
        if user_id is None or chat_id is None:
            return None
        return ParsedUpdate(
            kind="callback",
            external_user_id=str(user_id),
            chat_id=str(chat_id),
            display_name=user.get("name") or "",
            callback_payload=callback.get("payload") or "",
        )

    if update_type == "bot_started":
        user = update.get("user") or {}
        user_id = user.get("user_id")
        chat_id = update.get("chat_id")
        if user_id is None or chat_id is None:
            return None
        return ParsedUpdate(
            kind="bot_started", external_user_id=str(user_id), chat_id=str(chat_id), display_name=user.get("name") or ""
        )

    return None


def _get_or_create_state(db: Session, external_user_id: str, chat_id: str) -> ChannelConversationState:
    state = (
        db.query(ChannelConversationState)
        .filter(ChannelConversationState.channel == Channel.MAX, ChannelConversationState.external_user_id == external_user_id)
        .first()
    )
    if state is None:
        state = ChannelConversationState(channel=Channel.MAX, external_user_id=external_user_id, chat_id=chat_id)
        db.add(state)
        db.flush()
    elif state.chat_id != chat_id:
        state.chat_id = chat_id
        db.add(state)
    return state


def _resolve_contact(db: Session, state: ChannelConversationState, parsed: ParsedUpdate) -> tuple[Contact, bool]:
    if state.contact_id is not None:
        contact = db.get(Contact, state.contact_id)
        if contact is not None:
            return contact, False

    existing = db.query(Contact).filter(Contact.max_id == parsed.external_user_id).first()
    if existing is not None:
        state.contact_id = existing.id
        db.add(state)
        return existing, False

    org = get_or_create_unknown_organization(db)
    contact = Contact(
        organization_id=org.id,
        full_name=parsed.display_name or "Пользователь MAX",
        max_id=parsed.external_user_id,
        is_confirmed=False,
    )
    db.add(contact)
    db.flush()
    state.contact_id = contact.id
    db.add(state)
    return contact, True


def _list_open_tickets(db: Session, contact: Contact) -> list[Ticket]:
    return (
        db.query(Ticket)
        .filter(Ticket.contact_id == contact.id, Ticket.status.in_(OPEN_TICKET_STATUSES))
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .all()
    )


def _send(config: MaxConfig, chat_id: str, text: str, buttons: list[list[dict]] | None = None) -> None:
    try:
        max_client.send_message(config.base_url, config.token, chat_id, text, buttons=buttons)
    except max_client.MaxApiError:
        logger.exception("MAX: ошибка отправки сообщения в чат %s", chat_id)


def _store_max_attachment(db: Session, message: Message, attachment: dict) -> None:
    """MAX attachments come back as typed payloads; only the ones exposing a
    direct fetch `url` can be downloaded without the platform's separate
    upload/token exchange, which isn't confirmed against a live bot yet - see
    module docstring. Others are logged and skipped rather than guessed at."""
    payload = attachment.get("payload") or {}
    url = payload.get("url")
    att_type = attachment.get("type", "unknown")
    if not url:
        logger.info("MAX: вложение типа %s без прямой ссылки - пропущено (docs/decisions.md)", att_type)
        return
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(url)
            response.raise_for_status()
            content = response.content
    except Exception:
        logger.exception("MAX: не удалось скачать вложение")
        return
    filename = payload.get("filename") or att_type
    db.add(attachments_service.store_attachment(message.id, filename, content, None))


def _append_message(db: Session, ticket: Ticket, contact: Contact, parsed: ParsedUpdate, ambiguous: bool = False) -> Message:
    message = messages_service.add_message(
        db,
        ticket,
        MessageCreate(direction=MessageDirection.INBOUND, body=parsed.text, channel=Channel.MAX),
        author_contact=contact,
    )
    for att in parsed.attachments:
        _store_max_attachment(db, message, att)
    if ambiguous:
        messages_service.add_message(
            db,
            ticket,
            MessageCreate(
                direction=MessageDirection.INTERNAL_NOTE,
                body=(
                    "Автоматически привязано к последней активной заявке — у контакта несколько открытых "
                    "заявок, ответ в MAX не выбрал конкретную кнопкой. Уточните у диспетчера/клиента."
                ),
                channel=Channel.MAX,
            ),
        )
    return message


def _create_ticket_from_text(db: Session, config: MaxConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> Ticket:
    subject = parsed.text[:200] if parsed.text else "Обращение из MAX"
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.MAX,
        subject=subject,
        manual_priority=Priority.P3,
        manual_priority_reason="Автоматически создано из MAX - приоритет уточняется диспетчером",
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    message = messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body=parsed.text, channel=Channel.MAX), author_contact=contact
    )
    for att in parsed.attachments:
        _store_max_attachment(db, message, att)

    state.active_ticket_id = ticket.id
    db.add(state)
    db.commit()
    _send(config, parsed.chat_id, f"Заявка {ticket.display_number} создана, мы уже работаем над ней.")
    return ticket


def _send_ticket_choice(config: MaxConfig, chat_id: str, open_tickets: list[Ticket]) -> None:
    buttons = [[{"type": "callback", "text": f"{t.display_number} — {t.subject[:30]}", "payload": f"ticket:{t.id}"}] for t in open_tickets]
    buttons.append([{"type": "callback", "text": "Создать новую", "payload": "new_ticket"}])
    _send(config, chat_id, "У вас несколько открытых заявок. К какой относится сообщение?", buttons=buttons)


def _send_my_tickets(db: Session, config: MaxConfig, contact: Contact, chat_id: str) -> None:
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).order_by(Ticket.created_at.desc()).limit(10).all()
    if not tickets:
        _send(config, chat_id, "У вас пока нет заявок.")
        return
    buttons = [
        [{"type": "callback", "text": f"{t.display_number} — {_STATUS_LABELS_RU.get(TicketStatus(t.status), t.status)}", "payload": f"ticket:{t.id}"}]
        for t in tickets
    ]
    _send(config, chat_id, "Ваши заявки:", buttons=buttons)


def _handle_text(db: Session, config: MaxConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    text_lower = parsed.text.strip().lower()

    if state.awaiting_new_ticket_text:
        state.awaiting_new_ticket_text = False
        db.add(state)
        _create_ticket_from_text(db, config, state, contact, parsed)
        return

    if text_lower in MY_TICKETS_COMMANDS:
        _send_my_tickets(db, config, contact, parsed.chat_id)
        return

    if text_lower in NEW_TICKET_COMMANDS:
        state.awaiting_new_ticket_text = True
        state.awaiting_ticket_choice = False
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, "Опишите проблему одним сообщением - я создам заявку.")
        return

    # Dialog gluing rule (section 2, item 3): stick to the client's active
    # ticket until they switch (via "Мои заявки") or it stops being open.
    if state.active_ticket_id is not None:
        active = db.get(Ticket, state.active_ticket_id)
        if active is not None and TicketStatus(active.status) in OPEN_TICKET_STATUSES:
            _append_message(db, active, contact, parsed)
            db.commit()
            return
        state.active_ticket_id = None

    open_tickets = _list_open_tickets(db, contact)
    if len(open_tickets) == 1:
        state.active_ticket_id = open_tickets[0].id
        db.add(state)
        _append_message(db, open_tickets[0], contact, parsed)
        db.commit()
        return

    if len(open_tickets) > 1:
        if state.awaiting_ticket_choice:
            # Client replied with free text instead of pressing a button -
            # same email-channel fallback (docs/decisions.md): most recently
            # active ticket, flagged for dispatcher review.
            state.awaiting_ticket_choice = False
            state.active_ticket_id = open_tickets[0].id
            db.add(state)
            _append_message(db, open_tickets[0], contact, parsed, ambiguous=True)
            db.commit()
            return
        state.awaiting_ticket_choice = True
        db.add(state)
        db.commit()
        _send_ticket_choice(config, parsed.chat_id, open_tickets)
        return

    _create_ticket_from_text(db, config, state, contact, parsed)


def _record_csat(db: Session, config: MaxConfig, ticket_id: int, rating: int, chat_id: str) -> None:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        return
    if ticket.csat_rating is not None:
        _send(config, chat_id, "Спасибо, оценка уже получена ранее.")
        return
    ticket.csat_rating = max(1, min(5, rating))
    ticket.csat_rated_at = datetime.now(timezone.utc)
    db.add(ticket)
    db.commit()
    _send(config, chat_id, "Спасибо за оценку!")


def _handle_callback(db: Session, config: MaxConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    payload = parsed.callback_payload

    if payload == "new_ticket":
        state.awaiting_ticket_choice = False
        state.awaiting_new_ticket_text = True
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, "Опишите проблему одним сообщением - я создам заявку.")
        return

    if payload.startswith("ticket:"):
        ticket = db.get(Ticket, int(payload.split(":", 1)[1]))
        if ticket is None or ticket.contact_id != contact.id:
            _send(config, parsed.chat_id, "Заявка не найдена.")
            return
        state.active_ticket_id = ticket.id
        state.awaiting_ticket_choice = False
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, f"Переключено на {ticket.display_number} — {ticket.subject}. Пишите сюда.")
        return

    if payload.startswith("csat:"):
        _, ticket_id_str, rating_str = payload.split(":")
        _record_csat(db, config, int(ticket_id_str), int(rating_str), parsed.chat_id)
        return

    logger.warning("MAX: неизвестный callback payload=%r", payload)


def handle_update(db: Session, raw_update: dict) -> None:
    parsed = _extract_incoming(raw_update)
    if parsed is None:
        logger.warning("MAX: не удалось разобрать update (update_type=%r)", raw_update.get("update_type"))
        return

    config = load_max_config(db)
    if config is None:
        return

    state = _get_or_create_state(db, parsed.external_user_id, parsed.chat_id)
    contact, _ = _resolve_contact(db, state, parsed)
    db.commit()

    if parsed.kind == "bot_started":
        _send(config, parsed.chat_id, WELCOME_TEXT)
        return
    if parsed.kind == "callback":
        _handle_callback(db, config, state, contact, parsed)
        return
    _handle_text(db, config, state, contact, parsed)


def poll_updates(db: Session, config: MaxConfig) -> int:
    marker = get_marker(db)
    updates, next_marker = max_client.get_updates(config.base_url, config.token, marker, timeout=config.poll_timeout_seconds)
    for update in updates:
        try:
            handle_update(db, update)
        except Exception:
            logger.exception("MAX: ошибка обработки update")
    save_marker(db, next_marker)
    return len(updates)


def request_csat(db: Session, ticket: Ticket) -> None:
    """Called on Ticket -> CLOSED (services/tickets.transition_status) for
    every channel; only acts when the ticket's contact has a known MAX chat."""
    if Channel(ticket.channel) != Channel.MAX:
        return
    config = load_max_config(db)
    if config is None:
        return
    state = (
        db.query(ChannelConversationState)
        .filter(ChannelConversationState.channel == Channel.MAX, ChannelConversationState.contact_id == ticket.contact_id)
        .order_by(ChannelConversationState.updated_at.desc())
        .first()
    )
    if state is None:
        return
    buttons = [[{"type": "callback", "text": str(n), "payload": f"csat:{ticket.id}:{n}"} for n in range(1, 6)]]
    try:
        max_client.send_message(
            config.base_url,
            config.token,
            state.chat_id,
            f"Заявка {ticket.display_number} закрыта. Оцените, пожалуйста, качество решения от 1 до 5.",
            buttons=buttons,
        )
        ticket.csat_requested_at = datetime.now(timezone.utc)
        db.add(ticket)
        db.commit()
    except Exception:
        logger.exception("MAX: не удалось отправить запрос оценки по заявке %s", ticket.display_number)


def try_send_outbound(db: Session, ticket: Ticket, message: Message) -> None:
    config = load_max_config(db)
    if config is None:
        logger.warning("Заявка %s: канал MAX не настроен, сообщение не отправлено", ticket.display_number)
        return
    state = (
        db.query(ChannelConversationState)
        .filter(ChannelConversationState.channel == Channel.MAX, ChannelConversationState.contact_id == ticket.contact_id)
        .order_by(ChannelConversationState.updated_at.desc())
        .first()
    )
    if state is None:
        logger.warning("Заявка %s: нет сохранённого MAX-чата для контакта, сообщение не отправлено", ticket.display_number)
        return
    try:
        max_client.send_message(config.base_url, config.token, state.chat_id, message.body)
    except Exception:
        logger.exception("Заявка %s: ошибка отправки сообщения в MAX", ticket.display_number)
