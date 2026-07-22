"""Stage 5 MAX channel tests: update parsing, sender/thread resolution rules
mirroring the email channel's, "Мои заявки" ticket switching, explicit
new-ticket creation, and CSAT capture. The MAX HTTP client is always faked -
there is no live bot token in this environment (see docs/decisions.md)."""

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact
from app.models.message import Message
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.schemas.ticket import TicketCreate
from app.services import integration_settings, max_channel
from app.services import tickets as tickets_service


@pytest.fixture(autouse=True)
def _fake_send(monkeypatch):
    sent = []

    def _fake(base_url, token, chat_id, text, buttons=None):
        sent.append({"chat_id": chat_id, "text": text, "buttons": buttons})
        return {"message_id": "fake"}

    monkeypatch.setattr("app.services.max_channel.max_client.send_message", _fake)
    return sent


@pytest.fixture()
def max_enabled(db: Session):
    integration_settings.upsert(
        db,
        Channel.MAX,
        IntegrationSettingUpdate(is_enabled=True, config={"poll_timeout_seconds": 20}, secrets={"bot_token": "test-token"}),
    )
    return max_channel.load_max_config(db)


def _text_update(user_id="u1", chat_id="c1", text="Привет", name="Клиент MAX") -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "name": name},
            "recipient": {"chat_id": chat_id},
            "body": {"text": text, "attachments": []},
        },
    }


def _callback_update(user_id="u1", chat_id="c1", payload="new_ticket", name="Клиент MAX") -> dict:
    return {
        "update_type": "message_callback",
        "callback": {"user": {"user_id": user_id, "name": name}, "payload": payload},
        "message": {"recipient": {"chat_id": chat_id}},
    }


def _bot_started_update(user_id="u1", chat_id="c1", name="Клиент MAX") -> dict:
    return {"update_type": "bot_started", "user": {"user_id": user_id, "name": name}, "chat_id": chat_id}


# --- parsing -------------------------------------------------------


def test_extract_message_created():
    parsed = max_channel._extract_incoming(_text_update(text="Не работает 1С"))
    assert parsed.kind == "text"
    assert parsed.external_user_id == "u1"
    assert parsed.chat_id == "c1"
    assert parsed.text == "Не работает 1С"
    assert parsed.display_name == "Клиент MAX"


def test_extract_message_callback():
    parsed = max_channel._extract_incoming(_callback_update(payload="ticket:42"))
    assert parsed.kind == "callback"
    assert parsed.callback_payload == "ticket:42"
    assert parsed.chat_id == "c1"


def test_extract_bot_started():
    parsed = max_channel._extract_incoming(_bot_started_update())
    assert parsed.kind == "bot_started"
    assert parsed.external_user_id == "u1"


def test_extract_unknown_type_returns_none():
    assert max_channel._extract_incoming({"update_type": "chat_title_changed"}) is None


def test_extract_missing_sender_returns_none():
    assert max_channel._extract_incoming({"update_type": "message_created", "message": {"body": {"text": "hi"}}}) is None


# --- bot_started -------------------------------------------------------


def test_bot_started_sends_welcome(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _bot_started_update())
    assert len(_fake_send) == 1
    assert "Открытые Горизонты" in _fake_send[0]["text"] or "поддержки" in _fake_send[0]["text"]


# --- contact resolution -------------------------------------------------------


def test_resolve_contact_exact_max_id_match(db: Session, contact: Contact):
    contact.max_id = "u-known"
    db.commit()
    state = max_channel._get_or_create_state(db, "u-known", "chat-1")
    resolved, created = max_channel._resolve_contact(db, state, max_channel.ParsedUpdate(
        kind="text", external_user_id="u-known", chat_id="chat-1", display_name="X"
    ))
    assert created is False
    assert resolved.id == contact.id


def test_resolve_contact_unknown_goes_to_unknown_queue(db: Session):
    state = max_channel._get_or_create_state(db, "u-new", "chat-2")
    resolved, created = max_channel._resolve_contact(
        db, state, max_channel.ParsedUpdate(kind="text", external_user_id="u-new", chat_id="chat-2", display_name="Новый")
    )
    assert created is True
    assert resolved.is_confirmed is False
    assert resolved.max_id == "u-new"
    org = db.get(Organization, resolved.organization_id)
    assert org.name == "Неизвестные"


# --- end-to-end dialog handling -------------------------------------------------------


def test_first_message_from_new_contact_creates_ticket(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _text_update(user_id="u10", chat_id="c10", text="Не работает принтер"))

    contact = db.query(Contact).filter(Contact.max_id == "u10").first()
    assert contact is not None
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    assert ticket is not None
    assert ticket.subject == "Не работает принтер"
    assert ticket.channel == Channel.MAX
    assert ticket.priority == "P3"

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u10").first()
    assert state.active_ticket_id == ticket.id

    message = db.query(Message).filter(Message.ticket_id == ticket.id).first()
    assert message.direction == MessageDirection.INBOUND
    assert message.channel == Channel.MAX


def test_second_message_attaches_to_active_ticket(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _text_update(user_id="u11", chat_id="c11", text="Первое сообщение"))
    max_channel.handle_update(db, _text_update(user_id="u11", chat_id="c11", text="Второе сообщение"))

    contact = db.query(Contact).filter(Contact.max_id == "u11").first()
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).all()
    assert len(tickets) == 1  # no duplicate ticket created
    messages = db.query(Message).filter(Message.ticket_id == tickets[0].id, Message.direction == MessageDirection.INBOUND).all()
    assert len(messages) == 2


def test_multiple_open_tickets_prompts_choice_then_switches(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u12"
    db.commit()
    for subject in ("Заявка А", "Заявка Б"):
        payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject=subject, manual_priority=Priority.P3, manual_priority_reason="test")
        tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, _text_update(user_id="u12", chat_id="c12", text="К какой заявке это относится?"))

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u12").first()
    assert state.awaiting_ticket_choice is True
    assert state.active_ticket_id is None
    assert _fake_send[-1]["buttons"] is not None  # choice buttons were sent

    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).order_by(Ticket.id).all()
    chosen = tickets[0]
    max_channel.handle_update(db, max_channel_callback_for(chosen.id, user_id="u12", chat_id="c12"))

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u12").first()
    assert state.active_ticket_id == chosen.id
    assert state.awaiting_ticket_choice is False


def max_channel_callback_for(ticket_id: int, user_id: str, chat_id: str) -> dict:
    return _callback_update(user_id=user_id, chat_id=chat_id, payload=f"ticket:{ticket_id}")


def test_multiple_open_tickets_plain_reply_falls_back_ambiguous(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u13"
    db.commit()
    created_tickets = []
    for subject in ("Заявка А", "Заявка Б"):
        payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject=subject, manual_priority=Priority.P3, manual_priority_reason="test")
        created_tickets.append(tickets_service.create_ticket(db, payload, actor=None))

    max_channel.handle_update(db, _text_update(user_id="u13", chat_id="c13", text="Первое сообщение"))
    # Client answers with plain text instead of pressing a button.
    max_channel.handle_update(db, _text_update(user_id="u13", chat_id="c13", text="Это про первую проблему"))

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u13").first()
    assert state.awaiting_ticket_choice is False
    assert state.active_ticket_id is not None

    notes = (
        db.query(Message)
        .filter(Message.ticket_id == state.active_ticket_id, Message.direction == MessageDirection.INTERNAL_NOTE)
        .all()
    )
    assert len(notes) == 1


def test_my_tickets_command_lists_tickets(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u14"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, _text_update(user_id="u14", chat_id="c14", text="Мои заявки"))

    assert any(s["buttons"] for s in _fake_send)


def test_explicit_new_ticket_command_then_description(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u15"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Старая заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, _text_update(user_id="u15", chat_id="c15", text="новая заявка"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u15").first()
    assert state.awaiting_new_ticket_text is True

    max_channel.handle_update(db, _text_update(user_id="u15", chat_id="c15", text="Отдельная новая проблема"))
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).order_by(Ticket.id.desc()).all()
    assert tickets[0].subject == "Отдельная новая проблема"

    db.refresh(state)
    assert state.awaiting_new_ticket_text is False
    assert state.active_ticket_id == tickets[0].id


def test_new_ticket_button_callback_then_description(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _callback_update(user_id="u16", chat_id="c16", payload="new_ticket"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u16").first()
    assert state.awaiting_new_ticket_text is True

    max_channel.handle_update(db, _text_update(user_id="u16", chat_id="c16", text="Проблема с доступом"))
    contact = db.query(Contact).filter(Contact.max_id == "u16").first()
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    assert ticket.subject == "Проблема с доступом"


# --- CSAT -------------------------------------------------------


def test_request_csat_sends_rating_buttons(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u17"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    # Register the MAX chat by simulating an inbound message first.
    max_channel.handle_update(db, _text_update(user_id="u17", chat_id="c17", text="Привет"))

    max_channel.request_csat(db, ticket)
    db.refresh(ticket)
    assert ticket.csat_requested_at is not None
    assert any(s["buttons"] for s in _fake_send)


def test_csat_callback_records_rating_once(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u18"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, _callback_update(user_id="u18", chat_id="c18", payload=f"csat:{ticket.id}:4"))
    db.refresh(ticket)
    assert ticket.csat_rating == 4
    assert ticket.csat_rated_at is not None

    # A second rating attempt must not overwrite the first.
    max_channel.handle_update(db, _callback_update(user_id="u18", chat_id="c18", payload=f"csat:{ticket.id}:1"))
    db.refresh(ticket)
    assert ticket.csat_rating == 4


def test_transition_to_closed_triggers_csat_request(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u19"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u19", chat_id="c19", text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()

    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    db.refresh(ticket)
    assert ticket.csat_requested_at is not None


# --- outbound -------------------------------------------------------


def test_try_send_outbound_uses_known_chat(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u20"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u20", chat_id="c20", text="Привет"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()

    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.MAX, body="Ответ инженера")
    db.add(msg)
    db.commit()

    _fake_send.clear()
    max_channel.try_send_outbound(db, ticket, msg)
    assert len(_fake_send) == 1
    assert _fake_send[0]["chat_id"] == "c20"
    assert _fake_send[0]["text"] == "Ответ инженера"


def test_try_send_outbound_without_known_chat_does_not_raise(db: Session, max_enabled, contact: Contact):
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.MAX, body="Ответ")
    db.add(msg)
    db.commit()
    max_channel.try_send_outbound(db, ticket, msg)  # no ChannelConversationState exists - must not raise
