"""Telegram messenger channel - same client-facing feature set as MAX
(max_channel.py): identification by Contact.telegram_id, dialog gluing,
"Мои заявки" ticket menu (view/create/revive a closed ticket), reply-to-
message quoting, client-initiated close, status/assignment notifications,
and post-closure CSAT. Business rules that must stay identical between the
two channels (status labels, the close-chain, bot vocabulary) live in
messenger_common.py; everything here is Telegram's own wire format, which
differs from MAX's in every place that bit us there: `chat_id` and
`reply_to_message_id` are genuine JSON body fields (no MAX-style query-param
surprise), a reply is a flat integer, not a nested `link` object, and
Telegram's own `/setMyCommands` is a long-established feature (unlike MAX's
/me/commands, confirmed live not to render as a menu - docs/decisions.md).
Verified end-to-end against a real bot token on 2026-07-31.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, OPEN_TICKET_STATUSES, Priority, TicketStatus, TicketType
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact, ContactPhone
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import attachments as attachments_service
from app.services import integration_settings
from app.services import messages as messages_service
from app.services import messenger_common
from app.services import telegram_client
from app.services import tickets as tickets_service
from app.services.messenger_common import (
    MY_TICKETS_COMMANDS,
    NEW_TICKET_COMMANDS,
    START_COMMANDS,
    STATUS_LABELS_RU,
    WELCOME_TEXT,
)
from app.services.unknown_queue import get_or_create_unknown_organization

logger = logging.getLogger("app.telegram_channel")


@dataclass
class TelegramConfig:
    token: str
    base_url: str
    poll_timeout_seconds: int


@dataclass
class ParsedUpdate:
    kind: str  # "text" | "callback"
    external_user_id: str
    chat_id: str
    display_name: str
    text: str = ""
    callback_payload: str = ""
    callback_query_id: str = ""
    attachments: list[dict] = field(default_factory=list)
    mid: int | None = None
    reply_to_mid: int | None = None


def _main_menu_buttons() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "Мои заявки", "payload": "cmd:my_tickets"}],
        [{"type": "callback", "text": "Создать новую", "payload": "cmd:new_ticket"}],
    ]


def _menu_buttons_for(ticket: Ticket | None) -> list[list[dict]]:
    """Main menu plus a "Закрыть заявку" row when there's a concrete
    still-open ticket in context - see max_channel._menu_buttons_for. Used
    only for the one-off ticket-created/ticket-switched confirmations below,
    not for routine per-message sends - see _close_button_for."""
    buttons = _main_menu_buttons()
    if ticket is not None and TicketStatus(ticket.status) in messenger_common.CLOSEABLE_STATUSES:
        buttons.append([{"type": "callback", "text": "Закрыть заявку", "payload": f"close:{ticket.id}"}])
    return buttons


def _close_button_for(ticket: Ticket) -> list[list[dict]] | None:
    """Telegram's persistent "/" command menu (setMyCommands) reliably shows
    "Мои заявки"/"Создать новую" (unlike MAX's /me/commands, confirmed live
    not to render - docs/decisions.md) - repeating those as inline buttons
    on every routine message is just noise the customer explicitly asked to
    drop. Only "Закрыть заявку" still needs an inline button here: it
    targets one specific ticket and can't be a static command."""
    if TicketStatus(ticket.status) in messenger_common.CLOSEABLE_STATUSES:
        return [[{"type": "callback", "text": "Закрыть заявку", "payload": f"close:{ticket.id}"}]]
    return None


def load_telegram_config(db: Session) -> TelegramConfig | None:
    setting = integration_settings.get(db, Channel.TELEGRAM)
    if setting is None or not setting.is_enabled:
        return None
    token = integration_settings.decrypt_secret(setting, "bot_token")
    if not token:
        return None
    cfg = setting.config or {}
    return TelegramConfig(
        token=token,
        base_url=cfg.get("base_url") or telegram_client.DEFAULT_BASE_URL,
        poll_timeout_seconds=int(cfg.get("poll_timeout_seconds") or 20),
    )


def get_offset(db: Session) -> int | None:
    setting = integration_settings.get(db, Channel.TELEGRAM)
    if setting is None:
        return None
    return (setting.config or {}).get("_offset")


def save_offset(db: Session, offset: int | None) -> None:
    if offset is None:
        return
    setting = integration_settings.get_or_create(db, Channel.TELEGRAM)
    cfg = dict(setting.config or {})
    cfg["_offset"] = offset
    setting.config = cfg
    db.add(setting)
    db.commit()


def _display_name(user: dict) -> str:
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part).strip()
    return name or user.get("username") or ""


def _extract_attachments(message: dict) -> list[dict]:
    attachments = []
    photos = message.get("photo") or []
    if photos:
        largest = max(photos, key=lambda p: p.get("file_size") or 0)
        attachments.append({"kind": "photo", "file_id": largest["file_id"], "filename": "photo.jpg"})
    document = message.get("document")
    if document:
        attachments.append(
            {
                "kind": "document",
                "file_id": document["file_id"],
                "filename": document.get("file_name") or "document",
                "mime_type": document.get("mime_type"),
            }
        )
    return attachments


def _is_private_chat(chat: dict) -> bool:
    """The support bot has `can_join_groups` enabled, so anyone can add it to a
    group - where every message would otherwise be parsed as a client request
    and turned into a ticket (found in audit). Support conversations are
    one-to-one by design (identification is per-user), so only private chats
    are processed. Absent `type` is treated as private: Telegram always sends
    it, and refusing to answer on a shape we failed to read would be worse
    than answering one stray group message."""
    return chat.get("type", "private") == "private"


def _extract_incoming(update: dict) -> ParsedUpdate | None:
    if "message" in update:
        message = update["message"] or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        user_id = sender.get("id")
        chat_id = chat.get("id")
        if user_id is None or chat_id is None or not _is_private_chat(chat):
            return None
        reply_to = message.get("reply_to_message") or {}
        return ParsedUpdate(
            kind="text",
            external_user_id=str(user_id),
            chat_id=str(chat_id),
            display_name=_display_name(sender),
            text=(message.get("text") or "").strip(),
            attachments=_extract_attachments(message),
            mid=message.get("message_id"),
            reply_to_mid=reply_to.get("message_id"),
        )

    if "callback_query" in update:
        callback = update["callback_query"] or {}
        sender = callback.get("from") or {}
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        user_id = sender.get("id")
        chat_id = chat.get("id")
        if user_id is None or chat_id is None or not _is_private_chat(chat):
            return None
        return ParsedUpdate(
            kind="callback",
            external_user_id=str(user_id),
            chat_id=str(chat_id),
            display_name=_display_name(sender),
            callback_payload=callback.get("data") or "",
            callback_query_id=callback.get("id") or "",
        )

    return None


def _get_or_create_state(db: Session, external_user_id: str, chat_id: str) -> ChannelConversationState:
    state = (
        db.query(ChannelConversationState)
        .filter(
            ChannelConversationState.channel == Channel.TELEGRAM,
            ChannelConversationState.external_user_id == external_user_id,
        )
        .first()
    )
    if state is None:
        state = ChannelConversationState(channel=Channel.TELEGRAM, external_user_id=external_user_id, chat_id=chat_id)
        db.add(state)
        db.flush()
    elif state.chat_id != chat_id:
        state.chat_id = chat_id
        db.add(state)
    return state


def _create_unconfirmed_contact(db: Session, external_user_id: str, display_name: str) -> Contact:
    org = get_or_create_unknown_organization(db)
    contact = Contact(
        organization_id=org.id,
        full_name=display_name or "Пользователь Telegram",
        telegram_id=external_user_id,
        is_confirmed=False,
    )
    db.add(contact)
    db.flush()
    return contact


def _resolve_contact(db: Session, state: ChannelConversationState, parsed: ParsedUpdate) -> tuple[Contact, bool]:
    if state.contact_id is not None:
        contact = db.get(Contact, state.contact_id)
        if contact is not None:
            return contact, False

    existing = db.query(Contact).filter(Contact.telegram_id == parsed.external_user_id).first()
    if existing is not None:
        state.contact_id = existing.id
        db.add(state)
        return existing, False

    contact = _create_unconfirmed_contact(db, parsed.external_user_id, parsed.display_name)
    state.contact_id = contact.id
    db.add(state)
    return contact, True


def _handle_link_phone_reply(db: Session, config: TelegramConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    """See max_channel._handle_link_phone_reply - identical, non-blocking
    cross-channel identity matching, Telegram side."""
    state.awaiting_phone_confirmation = False
    db.add(state)
    matched = messenger_common.find_contact_by_phone(db, parsed.text)
    if matched is not None and matched.id != contact.id:
        messenger_common.merge_contacts(db, from_contact=contact, into_contact=matched)
        state.contact_id = matched.id
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, "Готово! Ваши предыдущие обращения объединены с этой перепиской.")
        return
    db.add(ContactPhone(contact_id=contact.id, phone=parsed.text.strip(), is_primary=not contact.phones))
    db.commit()
    _send(config, parsed.chat_id, "Спасибо, сохранили номер. Если найдём совпадение с другим каналом — объединим обращения.")


def _list_open_tickets(db: Session, contact: Contact) -> list[Ticket]:
    return (
        db.query(Ticket)
        .filter(Ticket.contact_id == contact.id, Ticket.status.in_(OPEN_TICKET_STATUSES))
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .all()
    )


def _send(
    config: TelegramConfig, chat_id: str, text: str, buttons: list[list[dict]] | None = None, reply_to_mid: int | None = None
) -> dict | None:
    try:
        return telegram_client.send_message(
            config.base_url, config.token, chat_id, text, buttons=buttons, reply_to_message_id=reply_to_mid
        )
    except telegram_client.TelegramApiError:
        logger.exception("Telegram: ошибка отправки сообщения в чат %s", chat_id)
        return None


def _store_telegram_attachment(db: Session, message: Message, config: TelegramConfig, attachment: dict) -> None:
    try:
        file_path = telegram_client.get_file_path(config.base_url, config.token, attachment["file_id"])
        if not file_path:
            return
        content = telegram_client.download_file(config.base_url, config.token, file_path)
    except Exception:
        logger.exception("Telegram: не удалось скачать вложение")
        return
    db.add(attachments_service.store_attachment(message.id, attachment["filename"], content, attachment.get("mime_type")))


def _resolve_reply_target(db: Session, ticket_id: int, reply_to_mid: int | None) -> int | None:
    if not reply_to_mid:
        return None
    parent = db.query(Message).filter(Message.telegram_message_id == reply_to_mid, Message.ticket_id == ticket_id).first()
    return parent.id if parent else None


def _acknowledge_gluing(config: TelegramConfig, chat_id: str, ticket: Ticket) -> None:
    """See max_channel._acknowledge_gluing for why this ack exists at all.
    Unlike MAX, the main menu itself doesn't need repeating here - Telegram's
    persistent command menu already covers it (see _close_button_for)."""
    _send(config, chat_id, f"Принято по заявке {ticket.display_number}.", buttons=_close_button_for(ticket))


def _append_message(db: Session, config: TelegramConfig, ticket: Ticket, contact: Contact, parsed: ParsedUpdate, ambiguous: bool = False) -> Message:
    message = messages_service.add_message(
        db,
        ticket,
        MessageCreate(
            direction=MessageDirection.INBOUND,
            body=parsed.text,
            channel=Channel.TELEGRAM,
            reply_to_message_id=_resolve_reply_target(db, ticket.id, parsed.reply_to_mid),
        ),
        author_contact=contact,
    )
    message.telegram_message_id = parsed.mid
    db.add(message)
    for att in parsed.attachments:
        _store_telegram_attachment(db, message, config, att)
    if ambiguous:
        messages_service.add_message(
            db,
            ticket,
            MessageCreate(
                direction=MessageDirection.INTERNAL_NOTE,
                body=(
                    "Автоматически привязано к последней активной заявке — у контакта несколько открытых "
                    "заявок, ответ в Telegram не выбрал конкретную кнопкой. Уточните у диспетчера/клиента."
                ),
                channel=Channel.TELEGRAM,
            ),
        )
    return message


def _create_ticket_from_text(
    db: Session,
    config: TelegramConfig,
    state: ChannelConversationState,
    contact: Contact,
    parsed: ParsedUpdate,
    parent_ticket_id: int | None = None,
) -> Ticket:
    subject = parsed.text[:200] if parsed.text else "Обращение из Telegram"
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.TELEGRAM,
        subject=subject,
        manual_priority=Priority.P3,
        manual_priority_reason="Автоматически создано из Telegram - приоритет уточняется диспетчером",
        parent_ticket_id=parent_ticket_id,
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    message = messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body=parsed.text, channel=Channel.TELEGRAM), author_contact=contact
    )
    message.telegram_message_id = parsed.mid
    db.add(message)
    for att in parsed.attachments:
        _store_telegram_attachment(db, message, config, att)

    state.active_ticket_id = ticket.id
    db.add(state)
    db.commit()
    parent = db.get(Ticket, parent_ticket_id) if parent_ticket_id is not None else None
    parent_note = f" и связана с {parent.display_number}" if parent else ""
    identity_hint = (
        "" if contact.is_confirmed else
        "\n\nЕсли вы уже писали нам из другого мессенджера, отправьте «связать телефон» - объединим историю обращений."
    )
    _send(
        config,
        parsed.chat_id,
        f"Заявка {ticket.display_number} создана{parent_note}, мы уже работаем над ней.{identity_hint}",
        buttons=_menu_buttons_for(ticket),
    )
    return ticket


def _send_ticket_choice(config: TelegramConfig, chat_id: str, open_tickets: list[Ticket]) -> None:
    buttons = [[{"type": "callback", "text": f"{t.display_number} — {t.subject[:30]}", "payload": f"ticket:{t.id}"}] for t in open_tickets]
    buttons.append([{"type": "callback", "text": "Создать новую", "payload": "new_ticket"}])
    _send(config, chat_id, "У вас несколько открытых заявок. К какой относится сообщение?", buttons=buttons)


def _send_my_tickets(db: Session, config: TelegramConfig, contact: Contact, chat_id: str) -> None:
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).order_by(Ticket.created_at.desc()).limit(10).all()
    if not tickets:
        _send(config, chat_id, "У вас пока нет заявок.")
        return
    open_tickets = [t for t in tickets if TicketStatus(t.status) in OPEN_TICKET_STATUSES]
    closed_tickets = [t for t in tickets if TicketStatus(t.status) not in OPEN_TICKET_STATUSES]
    buttons = [
        [
            {
                "type": "callback",
                "text": f"{t.display_number} — {t.subject[:30]} ({STATUS_LABELS_RU.get(TicketStatus(t.status), t.status)})",
                "payload": f"ticket:{t.id}",
            }
        ]
        for t in open_tickets + closed_tickets
    ]
    _send(config, chat_id, f"Ваши заявки (открытых: {len(open_tickets)} из {len(tickets)}):", buttons=buttons)


def _cancel_pending_ticket_flow(state: ChannelConversationState) -> None:
    """See max_channel._cancel_pending_ticket_flow - same fix, same reason:
    a recognized command must never be swallowed as ticket-description text."""
    state.awaiting_ticket_choice = False
    state.awaiting_new_ticket_text = False
    state.awaiting_revive_text = False
    state.revive_parent_ticket_id = None
    state.awaiting_phone_confirmation = False


def _handle_text(db: Session, config: TelegramConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    text_lower = parsed.text.strip().lower()

    if text_lower in START_COMMANDS:
        _cancel_pending_ticket_flow(state)
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, WELCOME_TEXT, buttons=_main_menu_buttons())
        return

    if text_lower in MY_TICKETS_COMMANDS:
        _cancel_pending_ticket_flow(state)
        db.add(state)
        db.commit()
        _send_my_tickets(db, config, contact, parsed.chat_id)
        return

    if text_lower in NEW_TICKET_COMMANDS:
        _cancel_pending_ticket_flow(state)
        state.awaiting_new_ticket_text = True
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, "Опишите проблему одним сообщением - я создам заявку.")
        return

    if text_lower in messenger_common.LINK_PHONE_COMMANDS:
        _cancel_pending_ticket_flow(state)
        state.awaiting_phone_confirmation = True
        db.add(state)
        db.commit()
        _send(config, parsed.chat_id, "Укажите, пожалуйста, номер телефона, под которым вы писали нам ранее.")
        return

    if state.awaiting_phone_confirmation:
        _handle_link_phone_reply(db, config, state, contact, parsed)
        return

    if state.awaiting_revive_text:
        state.awaiting_revive_text = False
        parent_ticket_id = state.revive_parent_ticket_id
        state.revive_parent_ticket_id = None
        db.add(state)
        _create_ticket_from_text(db, config, state, contact, parsed, parent_ticket_id=parent_ticket_id)
        return

    if state.awaiting_new_ticket_text:
        state.awaiting_new_ticket_text = False
        db.add(state)
        _create_ticket_from_text(db, config, state, contact, parsed)
        return

    # Dialog gluing rule (section 2, item 3): stick to the client's active
    # ticket until they switch (via "Мои заявки") or it stops being open.
    if state.active_ticket_id is not None:
        active = db.get(Ticket, state.active_ticket_id)
        if active is not None and TicketStatus(active.status) in OPEN_TICKET_STATUSES:
            _append_message(db, config, active, contact, parsed)
            db.commit()
            _acknowledge_gluing(config, parsed.chat_id, active)
            return
        state.active_ticket_id = None

    open_tickets = _list_open_tickets(db, contact)
    if len(open_tickets) == 1:
        state.active_ticket_id = open_tickets[0].id
        db.add(state)
        _append_message(db, config, open_tickets[0], contact, parsed)
        db.commit()
        _acknowledge_gluing(config, parsed.chat_id, open_tickets[0])
        return

    if len(open_tickets) > 1:
        if state.awaiting_ticket_choice:
            state.awaiting_ticket_choice = False
            state.active_ticket_id = open_tickets[0].id
            db.add(state)
            _append_message(db, config, open_tickets[0], contact, parsed, ambiguous=True)
            db.commit()
            _acknowledge_gluing(config, parsed.chat_id, open_tickets[0])
            return
        state.awaiting_ticket_choice = True
        db.add(state)
        db.commit()
        _send_ticket_choice(config, parsed.chat_id, open_tickets)
        return

    _create_ticket_from_text(db, config, state, contact, parsed)


def _record_csat(db: Session, config: TelegramConfig, ticket_id: int, rating: int, chat_id: str) -> None:
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


def _handle_callback(db: Session, config: TelegramConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    if parsed.callback_query_id:
        try:
            telegram_client.answer_callback_query(config.base_url, config.token, parsed.callback_query_id)
        except telegram_client.TelegramApiError:
            logger.exception("Telegram: не удалось подтвердить callback_query")

    payload = parsed.callback_payload

    if payload == "cmd:my_tickets":
        _send_my_tickets(db, config, contact, parsed.chat_id)
        return

    if payload.startswith("close:"):
        ticket = db.get(Ticket, int(payload.split(":", 1)[1]))
        if ticket is None or ticket.contact_id != contact.id:
            _send(config, parsed.chat_id, "Заявка не найдена.")
            return
        if TicketStatus(ticket.status) not in messenger_common.CLOSEABLE_STATUSES:
            _send(config, parsed.chat_id, f"Заявка {ticket.display_number} уже закрыта.")
            return
        messenger_common.close_ticket_chain(db, ticket)
        return

    if payload in ("new_ticket", "cmd:new_ticket"):
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
        if TicketStatus(ticket.status) not in OPEN_TICKET_STATUSES:
            state.awaiting_ticket_choice = False
            state.awaiting_revive_text = True
            state.revive_parent_ticket_id = ticket.id
            db.add(state)
            db.commit()
            _send(
                config,
                parsed.chat_id,
                f"Заявка {ticket.display_number} закрыта. Опишите, что случилось - я создам новую заявку и свяжу её с {ticket.display_number}.",
            )
            return
        state.active_ticket_id = ticket.id
        state.awaiting_ticket_choice = False
        db.add(state)
        db.commit()
        _send(
            config,
            parsed.chat_id,
            f"Переключено на {ticket.display_number} — {ticket.subject}. Пишите сюда.",
            buttons=_menu_buttons_for(ticket),
        )
        return

    if payload.startswith("csat:"):
        _, ticket_id_str, rating_str = payload.split(":")
        _record_csat(db, config, int(ticket_id_str), int(rating_str), parsed.chat_id)
        return

    logger.warning("Telegram: неизвестный callback payload=%r", payload)


_LINK_CODE_PATTERN = re.compile(r"^/link\s+(\S+)$", re.IGNORECASE)


def _try_link_engineer(db: Session, config: TelegramConfig, parsed: ParsedUpdate) -> bool:
    """Self-service staff linking (section 8: "инженер привязывает свой TG в
    профиле"), handled entirely separately from the client dialog below -
    an engineer's own User account, not a Contact, and must never fall
    through to creating a ticket out of a stray "/link ..." message. Returns
    True if this update was a link attempt (handled either way, valid code
    or not) so the caller skips the normal client flow."""
    if parsed.kind != "text":
        return False
    match = _LINK_CODE_PATTERN.match(parsed.text.strip())
    if not match:
        return False
    code = match.group(1).upper()
    user = (
        db.query(User)
        .filter(User.telegram_link_code == code, User.telegram_link_code_expires_at > datetime.now(timezone.utc))
        .first()
    )
    if user is None:
        _send(config, parsed.chat_id, "Код не найден или устарел. Получите новый код в профиле в веб-панели.")
        return True
    user.telegram_id = parsed.external_user_id
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    db.add(user)
    db.commit()
    _send(config, parsed.chat_id, f"Telegram успешно привязан к вашей учётной записи, {user.full_name}!")
    return True


def handle_update(db: Session, raw_update: dict) -> None:
    parsed = _extract_incoming(raw_update)
    if parsed is None:
        return

    config = load_telegram_config(db)
    if config is None:
        return

    if _try_link_engineer(db, config, parsed):
        return

    state = _get_or_create_state(db, parsed.external_user_id, parsed.chat_id)
    contact, _ = _resolve_contact(db, state, parsed)
    db.commit()

    if parsed.kind == "callback":
        _handle_callback(db, config, state, contact, parsed)
        return
    _handle_text(db, config, state, contact, parsed)


_commands_synced_token: str | None = None

BOT_COMMANDS = [
    {"command": "start", "description": "Показать меню"},
    {"command": "tickets", "description": "Мои заявки"},
    {"command": "new", "description": "Создать новую заявку"},
]


def _ensure_commands_registered(config: TelegramConfig) -> None:
    """setMyCommands once per (process, token) - unlike MAX's /me/commands
    (confirmed live not to render - docs/decisions.md), this is Telegram's
    own long-standing feature and reliably shows the "/" command menu."""
    global _commands_synced_token
    if _commands_synced_token == config.token:
        return
    try:
        telegram_client.set_commands(config.base_url, config.token, BOT_COMMANDS)
        _commands_synced_token = config.token
    except Exception:
        logger.exception("Telegram: не удалось зарегистрировать команды бота")


def poll_updates(db: Session, config: TelegramConfig) -> int:
    _ensure_commands_registered(config)
    offset = get_offset(db)
    updates = telegram_client.get_updates(config.base_url, config.token, offset, timeout=config.poll_timeout_seconds)
    next_offset = offset
    for update in updates:
        try:
            handle_update(db, update)
        except Exception:
            logger.exception("Telegram: ошибка обработки update")
        update_id = update.get("update_id")
        if update_id is not None:
            next_offset = update_id + 1
    save_offset(db, next_offset)
    return len(updates)


def _find_chat_state(db: Session, contact_id: int) -> ChannelConversationState | None:
    return (
        db.query(ChannelConversationState)
        .filter(ChannelConversationState.channel == Channel.TELEGRAM, ChannelConversationState.contact_id == contact_id)
        .order_by(ChannelConversationState.updated_at.desc())
        .first()
    )


def notify_status_change(db: Session, ticket: Ticket, new_status: TicketStatus) -> None:
    """See max_channel.notify_status_change - identical rule, Telegram side."""
    if Channel(ticket.channel) != Channel.TELEGRAM or new_status == TicketStatus.CLOSED:
        return
    config = load_telegram_config(db)
    if config is None:
        return
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        return
    label = STATUS_LABELS_RU.get(new_status, new_status.value)
    _send(config, state.chat_id, f"Статус заявки {ticket.display_number} изменён: {label}.")


def notify_assignment_change(db: Session, ticket: Ticket, engineer: User | None) -> None:
    if Channel(ticket.channel) != Channel.TELEGRAM or engineer is None:
        return
    config = load_telegram_config(db)
    if config is None:
        return
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        return
    _send(config, state.chat_id, f"Заявку {ticket.display_number} теперь ведёт: {engineer.full_name}.")


def request_csat(db: Session, ticket: Ticket) -> None:
    if Channel(ticket.channel) != Channel.TELEGRAM:
        return
    config = load_telegram_config(db)
    if config is None:
        return
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        return
    buttons = [[{"type": "callback", "text": str(n), "payload": f"csat:{ticket.id}:{n}"} for n in range(1, 6)]]
    try:
        telegram_client.send_message(
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
        logger.exception("Telegram: не удалось отправить запрос оценки по заявке %s", ticket.display_number)


def try_send_outbound(db: Session, ticket: Ticket, message: Message) -> None:
    config = load_telegram_config(db)
    if config is None:
        logger.warning("Заявка %s: канал Telegram не настроен, сообщение не отправлено", ticket.display_number)
        return
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        logger.warning("Заявка %s: нет сохранённого Telegram-чата для контакта, сообщение не отправлено", ticket.display_number)
        return
    reply_to_mid = None
    if message.reply_to_message_id is not None:
        parent = db.get(Message, message.reply_to_message_id)
        reply_to_mid = parent.telegram_message_id if parent else None
    try:
        # Unlike MAX (whose /me/commands menu doesn't render on every client
        # - docs/decisions.md), Telegram's persistent command menu already
        # covers "Мои заявки"/"Создать новую" reliably, so engineer replies
        # only need the ticket-specific close button, not the whole menu.
        response = telegram_client.send_message(
            config.base_url,
            config.token,
            state.chat_id,
            message.body,
            buttons=_close_button_for(ticket),
            reply_to_message_id=reply_to_mid,
        )
        sent_mid = response.get("message_id")
        if sent_mid:
            message.telegram_message_id = sent_mid
            db.add(message)
            db.commit()
    except Exception:
        logger.exception("Заявка %s: ошибка отправки сообщения в Telegram", ticket.display_number)
