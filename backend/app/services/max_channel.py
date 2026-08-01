"""MAX messenger channel (section 2.2: "Аналогично Telegram") - client-side
identification, dialog gluing, "Мои заявки" (ticket menu incl. reviving a
closed ticket), explicit new-ticket creation, reply-to-message quoting, and
post-closure CSAT (section 2.1's bot feature list, mirrored for MAX).

Update/Message JSON shapes were originally transcribed from the public MAX
Bot API docs (dev.max.ru/docs-api, 2026-07-22) with no live bot to verify
against; verified end-to-end against a real bot token on 2026-07-31 (inbound
+ outbound messages, the reply `link` shape, chat_id-as-query-param) - see
docs/decisions.md. All inbound parsing is isolated in `_extract_incoming` so
any remaining field-name gap is a one-function fix.
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
from app.models.contact import Contact, ContactPhone
from app.models.message import Message
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import attachments as attachments_service
from app.services import integration_settings
from app.services import max_client
from app.services import messages as messages_service
from app.services import messenger_common
from app.services import tickets as tickets_service
from app.services.messenger_common import (
    MY_TICKETS_COMMANDS,
    NEW_TICKET_COMMANDS,
    START_COMMANDS,
    STATUS_LABELS_RU as _STATUS_LABELS_RU,
    WELCOME_TEXT,
)
from app.services.unknown_queue import get_or_create_unknown_organization

logger = logging.getLogger("app.max_channel")


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
    mid: str | None = None
    reply_to_mid: str | None = None


def _main_menu_buttons() -> list[list[dict]]:
    return [
        [{"type": "callback", "text": "Мои заявки", "payload": "cmd:my_tickets"}],
        [{"type": "callback", "text": "Создать новую", "payload": "cmd:new_ticket"}],
    ]


def _menu_buttons_for(ticket: Ticket | None) -> list[list[dict]]:
    """Main menu plus a "Закрыть заявку" row when there's a concrete
    still-open ticket in context (client-initiated close, section 2
    request) - the bare welcome message and the "Мои заявки" listing have
    no single ticket to close, so they stay with `_main_menu_buttons()`."""
    buttons = _main_menu_buttons()
    if ticket is not None and TicketStatus(ticket.status) in messenger_common.CLOSEABLE_STATUSES:
        buttons.append([{"type": "callback", "text": "Закрыть заявку", "payload": f"close:{ticket.id}"}])
    return buttons


def _extract_link_mid(link: dict) -> str | None:
    """Reads a reply reference off an incoming message's `link` field.
    Confirmed live (2026-07-31, docs/decisions.md): MAX nests the original
    message under `link.message.mid`, not a flat `link.mid` - the flat form
    is kept as a fallback rather than assumed, in case a future update shape
    (e.g. from a different client) differs."""
    if not link or link.get("type") not in (None, "reply"):
        return None
    inner = link.get("message") or {}
    return inner.get("mid") or link.get("mid")


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


def _is_dialog(recipient: dict) -> bool:
    """Only one-to-one dialogs are treated as client conversations - a bot
    added to a group chat would otherwise turn every message there into a
    ticket (same guard as telegram_channel._is_private_chat). Real dialogs
    report `chat_type: "dialog"` (confirmed live); a missing value is treated
    as a dialog rather than dropped, so an unexpected shape never silences
    the bot entirely."""
    return recipient.get("chat_type", "dialog") == "dialog"


def _extract_incoming(update: dict) -> ParsedUpdate | None:
    update_type = update.get("update_type")

    if update_type == "message_created":
        message = update.get("message") or {}
        sender = message.get("sender") or {}
        recipient = message.get("recipient") or {}
        body = message.get("body") or {}
        user_id = sender.get("user_id")
        chat_id = recipient.get("chat_id")
        if user_id is None or chat_id is None or not _is_dialog(recipient):
            return None
        return ParsedUpdate(
            kind="text",
            external_user_id=str(user_id),
            chat_id=str(chat_id),
            display_name=sender.get("name") or sender.get("username") or "",
            text=(body.get("text") or "").strip(),
            attachments=body.get("attachments") or [],
            mid=body.get("mid"),
            reply_to_mid=_extract_link_mid(message.get("link") or {}),
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


def _create_unconfirmed_contact(db: Session, external_user_id: str, display_name: str) -> Contact:
    org = get_or_create_unknown_organization(db)
    contact = Contact(
        organization_id=org.id,
        full_name=display_name or "Пользователь MAX",
        max_id=external_user_id,
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

    existing = db.query(Contact).filter(Contact.max_id == parsed.external_user_id).first()
    if existing is not None:
        state.contact_id = existing.id
        db.add(state)
        return existing, False

    contact = _create_unconfirmed_contact(db, parsed.external_user_id, parsed.display_name)
    state.contact_id = contact.id
    db.add(state)
    return contact, True


def _handle_link_phone_reply(db: Session, config: MaxConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    """Cross-channel identity matching (по запросу заказчика), non-blocking
    variant: unlike gating every first message on a phone number (tried and
    reverted - would add friction to the overwhelmingly common case of a
    genuinely new contact, see docs/decisions.md), this only runs when the
    client explicitly opts in via LINK_PHONE_COMMANDS. A match merges this
    (possibly already ticket-bearing) contact into the existing one instead
    of the other way round - the client's current conversation continues
    against whichever contact survives."""
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


def _resolve_reply_target(db: Session, ticket_id: int, reply_to_mid: str | None) -> int | None:
    if not reply_to_mid:
        return None
    parent = db.query(Message).filter(Message.max_message_id == reply_to_mid, Message.ticket_id == ticket_id).first()
    return parent.id if parent else None


def _acknowledge_gluing(config: MaxConfig, chat_id: str, ticket: Ticket) -> None:
    """The silent-gluing path used to send nothing back at all, leaving the
    client with no visible confirmation the message arrived and no way to
    tell they could switch away - the exact confusion flagged live testing
    ("как выйти из диалога заявки, как снова открыть список заявок",
    docs/decisions.md). A one-line ack + the same main menu buttons used
    everywhere else fixes both without a special "exit" concept: switching
    tickets already works via "Мои заявки", it just needed to stay visible."""
    _send(config, chat_id, f"Принято по заявке {ticket.display_number}.", buttons=_menu_buttons_for(ticket))


def _append_message(db: Session, ticket: Ticket, contact: Contact, parsed: ParsedUpdate, ambiguous: bool = False) -> Message:
    message = messages_service.add_message(
        db,
        ticket,
        MessageCreate(
            direction=MessageDirection.INBOUND,
            body=parsed.text,
            channel=Channel.MAX,
            reply_to_message_id=_resolve_reply_target(db, ticket.id, parsed.reply_to_mid),
        ),
        author_contact=contact,
    )
    message.max_message_id = parsed.mid
    db.add(message)
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


def _create_ticket_from_text(
    db: Session,
    config: MaxConfig,
    state: ChannelConversationState,
    contact: Contact,
    parsed: ParsedUpdate,
    parent_ticket_id: int | None = None,
) -> Ticket:
    subject = parsed.text[:200] if parsed.text else "Обращение из MAX"
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.MAX,
        subject=subject,
        manual_priority=Priority.P3,
        manual_priority_reason="Автоматически создано из MAX - приоритет уточняется диспетчером",
        parent_ticket_id=parent_ticket_id,
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    message = messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body=parsed.text, channel=Channel.MAX), author_contact=contact
    )
    message.max_message_id = parsed.mid
    db.add(message)
    for att in parsed.attachments:
        _store_max_attachment(db, message, att)

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


def _send_ticket_choice(config: MaxConfig, chat_id: str, open_tickets: list[Ticket]) -> None:
    buttons = [[{"type": "callback", "text": f"{t.display_number} — {t.subject[:30]}", "payload": f"ticket:{t.id}"}] for t in open_tickets]
    buttons.append([{"type": "callback", "text": "Создать новую", "payload": "new_ticket"}])
    _send(config, chat_id, "У вас несколько открытых заявок. К какой относится сообщение?", buttons=buttons)


def _send_my_tickets(db: Session, config: MaxConfig, contact: Contact, chat_id: str) -> None:
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).order_by(Ticket.created_at.desc()).limit(10).all()
    if not tickets:
        _send(config, chat_id, "У вас пока нет заявок.")
        return
    # Structured for scanability: active tickets first (most likely to be
    # tapped), history below - a flat "created_at desc" list buried an open
    # ticket under recently-closed ones once there were more than a couple.
    open_tickets = [t for t in tickets if TicketStatus(t.status) in OPEN_TICKET_STATUSES]
    closed_tickets = [t for t in tickets if TicketStatus(t.status) not in OPEN_TICKET_STATUSES]
    buttons = [
        [
            {
                "type": "callback",
                "text": f"{t.display_number} — {t.subject[:30]} ({_STATUS_LABELS_RU.get(TicketStatus(t.status), t.status)})",
                "payload": f"ticket:{t.id}",
            }
        ]
        for t in open_tickets + closed_tickets
    ]
    _send(config, chat_id, f"Ваши заявки (открытых: {len(open_tickets)} из {len(tickets)}):", buttons=buttons)


def _cancel_pending_ticket_flow(state: ChannelConversationState) -> None:
    """Reset to a clean slate before honouring a recognized command. Without
    this, typing e.g. "/start" while the bot was waiting for a problem
    description got swallowed verbatim as that description - creating a
    ticket literally titled "/start" and silently switching the active
    ticket to it (found live: docs/decisions.md)."""
    state.awaiting_ticket_choice = False
    state.awaiting_new_ticket_text = False
    state.awaiting_revive_text = False
    state.revive_parent_ticket_id = None
    state.awaiting_phone_confirmation = False


def _handle_text(db: Session, config: MaxConfig, state: ChannelConversationState, contact: Contact, parsed: ParsedUpdate) -> None:
    text_lower = parsed.text.strip().lower()

    # Recognized commands always win over a pending "describe the problem"
    # prompt - see _cancel_pending_ticket_flow.
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
            _append_message(db, active, contact, parsed)
            db.commit()
            _acknowledge_gluing(config, parsed.chat_id, active)
            return
        state.active_ticket_id = None

    open_tickets = _list_open_tickets(db, contact)
    if len(open_tickets) == 1:
        state.active_ticket_id = open_tickets[0].id
        db.add(state)
        _append_message(db, open_tickets[0], contact, parsed)
        db.commit()
        _acknowledge_gluing(config, parsed.chat_id, open_tickets[0])
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
            _acknowledge_gluing(config, parsed.chat_id, open_tickets[0])
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
            # Terminal ticket ("поднять старую"): CLOSED/CANCELLED never
            # transition back open (ALLOWED_TRANSITIONS), so the next message
            # becomes a new ticket linked to this one via parent_ticket_id.
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
        _send(config, parsed.chat_id, WELCOME_TEXT, buttons=_main_menu_buttons())
        return
    if parsed.kind == "callback":
        _handle_callback(db, config, state, contact, parsed)
        return
    _handle_text(db, config, state, contact, parsed)


_commands_synced_token: str | None = None

BOT_COMMANDS = [
    {"name": "start", "description": "Показать меню"},
    {"name": "tickets", "description": "Мои заявки"},
    {"name": "new", "description": "Создать новую заявку"},
]


def _ensure_commands_registered(config: MaxConfig) -> None:
    """PATCH /me/commands once per (process, token) - a persistent command
    menu the client shows near the input field, so returning users have a
    tappable alternative to typing "/start" from memory (docs/decisions.md).
    Cheap to re-check every poll: memoized on the token, so it's a no-op
    after the first successful call; retried on the next poll if it fails."""
    global _commands_synced_token
    if _commands_synced_token == config.token:
        return
    try:
        max_client.set_commands(config.base_url, config.token, BOT_COMMANDS)
        _commands_synced_token = config.token
    except Exception:
        logger.exception("MAX: не удалось зарегистрировать команды бота")


def poll_updates(db: Session, config: MaxConfig) -> int:
    _ensure_commands_registered(config)
    marker = get_marker(db)
    updates, next_marker = max_client.get_updates(config.base_url, config.token, marker, timeout=config.poll_timeout_seconds)
    for update in updates:
        try:
            handle_update(db, update)
        except Exception:
            logger.exception("MAX: ошибка обработки update")
    save_marker(db, next_marker)
    return len(updates)


def _find_chat_state(db: Session, contact_id: int) -> ChannelConversationState | None:
    return (
        db.query(ChannelConversationState)
        .filter(ChannelConversationState.channel == Channel.MAX, ChannelConversationState.contact_id == contact_id)
        .order_by(ChannelConversationState.updated_at.desc())
        .first()
    )


def notify_status_change(db: Session, ticket: Ticket, new_status: TicketStatus) -> None:
    """Called on every transition (services/tickets.transition_status) so the
    client isn't left guessing where their ticket stands. Skipped for CLOSED -
    request_csat's own message already announces the closure, and skipped
    for channels other than MAX the same way request_csat is."""
    if Channel(ticket.channel) != Channel.MAX or new_status == TicketStatus.CLOSED:
        return
    config = load_max_config(db)
    if config is None:
        return
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        return
    label = _STATUS_LABELS_RU.get(new_status, new_status.value)
    _send(config, state.chat_id, f"Статус заявки {ticket.display_number} изменён: {label}.")


def notify_assignment_change(db: Session, ticket: Ticket, engineer: User | None) -> None:
    """Called from services/tickets.update_ticket when assigned_engineer_id
    changes - only fires for an actual assignment (there's currently no way
    to clear it back to None through that endpoint, see update_ticket)."""
    if Channel(ticket.channel) != Channel.MAX or engineer is None:
        return
    config = load_max_config(db)
    if config is None:
        return
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        return
    _send(config, state.chat_id, f"Заявку {ticket.display_number} теперь ведёт: {engineer.full_name}.")


def request_csat(db: Session, ticket: Ticket) -> None:
    """Called on Ticket -> CLOSED (services/tickets.transition_status) for
    every channel; only acts when the ticket's contact has a known MAX chat."""
    if Channel(ticket.channel) != Channel.MAX:
        return
    config = load_max_config(db)
    if config is None:
        return
    state = _find_chat_state(db, ticket.contact_id)
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
    state = _find_chat_state(db, ticket.contact_id)
    if state is None:
        logger.warning("Заявка %s: нет сохранённого MAX-чата для контакта, сообщение не отправлено", ticket.display_number)
        return
    reply_to_mid = None
    if message.reply_to_message_id is not None:
        parent = db.get(Message, message.reply_to_message_id)
        reply_to_mid = parent.max_message_id if parent else None
    try:
        # MAX doesn't render the registered /me/commands as a visible menu on
        # every client (confirmed live - docs/decisions.md), so the menu
        # buttons ride along on every engineer reply too, same as the
        # gluing ack (_acknowledge_gluing).
        response = max_client.send_message(
            config.base_url,
            config.token,
            state.chat_id,
            message.body,
            buttons=_menu_buttons_for(ticket),
            reply_to_mid=reply_to_mid,
        )
        sent_mid = ((response.get("message") or {}).get("body") or {}).get("mid")
        if sent_mid:
            message.max_message_id = sent_mid
            db.add(message)
            db.commit()
    except Exception:
        logger.exception("Заявка %s: ошибка отправки сообщения в MAX", ticket.display_number)
