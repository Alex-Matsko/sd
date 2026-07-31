"""Telegram channel tests, mirroring test_max_channel.py's coverage for the
shared feature set (dialog gluing, ticket menu incl. revive/close, reply
quoting, notifications) - see telegram_channel.py's module docstring for what
differs from MAX and why. The Telegram HTTP client is always faked; no live
token is used in this environment (see docs/decisions.md)."""

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact
from app.models.message import Message
from app.models.ticket import Ticket
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.schemas.ticket import TicketCreate
from app.services import integration_settings, telegram_channel
from app.services import tickets as tickets_service


@pytest.fixture(autouse=True)
def _fake_send(monkeypatch):
    sent = []

    def _fake(base_url, token, chat_id, text, buttons=None, reply_to_message_id=None):
        sent.append({"chat_id": chat_id, "text": text, "buttons": buttons, "reply_to_message_id": reply_to_message_id})
        return {"message_id": len(sent), "text": text}

    monkeypatch.setattr("app.services.telegram_channel.telegram_client.send_message", _fake)
    monkeypatch.setattr("app.services.telegram_channel.telegram_client.answer_callback_query", lambda *a, **k: None)
    return sent


@pytest.fixture()
def telegram_enabled(db: Session):
    integration_settings.upsert(
        db,
        Channel.TELEGRAM,
        IntegrationSettingUpdate(is_enabled=True, config={"poll_timeout_seconds": 20}, secrets={"bot_token": "test-token"}),
    )
    return telegram_channel.load_telegram_config(db)


def _text_update(user_id=1, chat_id=1, text="Привет", first_name="Клиент", mid=None, reply_mid=None) -> dict:
    message: dict = {
        "message_id": mid or 1,
        "from": {"id": user_id, "first_name": first_name},
        "chat": {"id": chat_id, "type": "private"},
        "text": text,
    }
    if reply_mid:
        message["reply_to_message"] = {"message_id": reply_mid}
    return {"update_id": 1, "message": message}


def _callback_update(user_id=1, chat_id=1, payload="new_ticket", first_name="Клиент", callback_id="cbq-1") -> dict:
    return {
        "update_id": 1,
        "callback_query": {
            "id": callback_id,
            "from": {"id": user_id, "first_name": first_name},
            "message": {"chat": {"id": chat_id}},
            "data": payload,
        },
    }


def _callback_for(ticket_id: int, user_id=1, chat_id=1) -> dict:
    return _callback_update(user_id=user_id, chat_id=chat_id, payload=f"ticket:{ticket_id}")


# --- parsing -------------------------------------------------------


def test_extract_message():
    parsed = telegram_channel._extract_incoming(_text_update(text="Не работает 1С", mid=42))
    assert parsed.kind == "text"
    assert parsed.external_user_id == "1"
    assert parsed.chat_id == "1"
    assert parsed.text == "Не работает 1С"
    assert parsed.mid == 42


def test_extract_message_with_reply():
    parsed = telegram_channel._extract_incoming(_text_update(text="Ответ", mid=2, reply_mid=1))
    assert parsed.reply_to_mid == 1


def test_extract_callback_query():
    parsed = telegram_channel._extract_incoming(_callback_update(payload="ticket:42"))
    assert parsed.kind == "callback"
    assert parsed.callback_payload == "ticket:42"
    assert parsed.callback_query_id == "cbq-1"


def test_extract_unknown_update_returns_none():
    assert telegram_channel._extract_incoming({"update_id": 1, "edited_message": {}}) is None


# --- end-to-end dialog handling -------------------------------------------------------


def test_first_message_creates_ticket(db: Session, telegram_enabled, _fake_send):
    telegram_channel.handle_update(db, _text_update(user_id=10, chat_id=10, text="Не работает принтер", mid=1))

    contact = db.query(Contact).filter(Contact.telegram_id == "10").first()
    assert contact is not None
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    assert ticket is not None
    assert ticket.subject == "Не работает принтер"
    assert ticket.channel == Channel.TELEGRAM

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "10").first()
    assert state.active_ticket_id == ticket.id

    message = db.query(Message).filter(Message.ticket_id == ticket.id).first()
    assert message.direction == MessageDirection.INBOUND
    assert message.telegram_message_id == 1


def test_second_message_attaches_and_acknowledges(db: Session, telegram_enabled, _fake_send):
    telegram_channel.handle_update(db, _text_update(user_id=11, chat_id=11, text="Первое", mid=1))
    _fake_send.clear()
    telegram_channel.handle_update(db, _text_update(user_id=11, chat_id=11, text="Второе", mid=2))

    contact = db.query(Contact).filter(Contact.telegram_id == "11").first()
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).all()
    assert len(tickets) == 1
    messages = db.query(Message).filter(Message.ticket_id == tickets[0].id, Message.direction == MessageDirection.INBOUND).all()
    assert len(messages) == 2

    assert len(_fake_send) == 1
    assert tickets[0].display_number in _fake_send[0]["text"]
    # Unlike MAX, no main-menu buttons here - Telegram's persistent command
    # menu already covers "Мои заявки"/"Создать новую" (docs/decisions.md).
    payloads = {row[0]["payload"] for row in _fake_send[0]["buttons"]}
    assert payloads == {f"close:{tickets[0].id}"}


def test_multiple_open_tickets_prompts_choice_then_switches(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "12"
    db.commit()
    for subject in ("Заявка А", "Заявка Б"):
        payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject=subject, manual_priority=Priority.P3, manual_priority_reason="test")
        tickets_service.create_ticket(db, payload, actor=None)

    telegram_channel.handle_update(db, _text_update(user_id=12, chat_id=12, text="К какой заявке это относится?"))

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "12").first()
    assert state.awaiting_ticket_choice is True

    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).order_by(Ticket.id).all()
    telegram_channel.handle_update(db, _callback_for(tickets[0].id, user_id=12, chat_id=12))

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "12").first()
    assert state.active_ticket_id == tickets[0].id
    assert state.awaiting_ticket_choice is False


def test_my_tickets_lists_subject_and_groups_open_first(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "13"
    db.commit()
    closed_payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Старая", manual_priority=Priority.P3, manual_priority_reason="test")
    closed = tickets_service.create_ticket(db, closed_payload, actor=None)
    tickets_service.transition_status(db, closed, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, closed, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, closed, TicketStatus.CLOSED, actor=None)
    open_payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Новая", manual_priority=Priority.P3, manual_priority_reason="test")
    open_ticket = tickets_service.create_ticket(db, open_payload, actor=None)

    telegram_channel.handle_update(db, _text_update(user_id=13, chat_id=13, text="Мои заявки"))

    last = _fake_send[-1]
    assert "открытых: 1 из 2" in last["text"]
    payloads_in_order = [row[0]["payload"] for row in last["buttons"]]
    assert payloads_in_order == [f"ticket:{open_ticket.id}", f"ticket:{closed.id}"]


# --- "поднять старую" -------------------------------------------------------


def test_selecting_closed_ticket_prompts_revive_then_creates_linked_ticket(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "14"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Старая проблема", manual_priority=Priority.P3, manual_priority_reason="test")
    old_ticket = tickets_service.create_ticket(db, payload, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.CLOSED, actor=None)

    telegram_channel.handle_update(db, _callback_for(old_ticket.id, user_id=14, chat_id=14))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "14").first()
    assert state.awaiting_revive_text is True
    assert state.revive_parent_ticket_id == old_ticket.id

    telegram_channel.handle_update(db, _text_update(user_id=14, chat_id=14, text="Проблема повторилась"))
    db.refresh(state)
    assert state.awaiting_revive_text is False

    new_ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id, Ticket.id != old_ticket.id).first()
    assert new_ticket.parent_ticket_id == old_ticket.id
    assert state.active_ticket_id == new_ticket.id


# --- commands must cancel a pending ticket-description prompt -------------------------------------------------------


def test_start_command_cancels_pending_new_ticket_flow(db: Session, telegram_enabled, _fake_send):
    telegram_channel.handle_update(db, _text_update(user_id=15, chat_id=15, text="новая заявка"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "15").first()
    assert state.awaiting_new_ticket_text is True

    telegram_channel.handle_update(db, _text_update(user_id=15, chat_id=15, text="/start"))
    db.refresh(state)
    assert state.awaiting_new_ticket_text is False

    contact = db.query(Contact).filter(Contact.telegram_id == "15").first()
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).all() if contact else []
    assert not any(t.subject == "/start" for t in tickets)


# --- reply-to-message -------------------------------------------------------


def test_inbound_reply_resolves_to_local_message(db: Session, telegram_enabled, _fake_send):
    telegram_channel.handle_update(db, _text_update(user_id=16, chat_id=16, text="Первое сообщение", mid=100))
    contact = db.query(Contact).filter(Contact.telegram_id == "16").first()
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    first_message = db.query(Message).filter(Message.ticket_id == ticket.id).first()
    assert first_message.telegram_message_id == 100

    telegram_channel.handle_update(db, _text_update(user_id=16, chat_id=16, text="Ответ на первое", mid=101, reply_mid=100))
    second_message = db.query(Message).filter(Message.ticket_id == ticket.id).order_by(Message.id.desc()).first()
    assert second_message.reply_to_message_id == first_message.id


def test_try_send_outbound_with_reply_passes_parent_mid_and_stores_own_mid(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "17"
    db.commit()
    telegram_channel.handle_update(db, _text_update(user_id=17, chat_id=17, text="Привет", mid=200))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    inbound = db.query(Message).filter(Message.ticket_id == ticket.id).first()

    reply = Message(
        ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.TELEGRAM, body="Уточните версию",
        reply_to_message_id=inbound.id,
    )
    db.add(reply)
    db.commit()

    _fake_send.clear()
    telegram_channel.try_send_outbound(db, ticket, reply)
    assert len(_fake_send) == 1
    assert _fake_send[0]["reply_to_message_id"] == 200
    db.refresh(reply)
    assert reply.telegram_message_id is not None
    # Only the close button here, not the full main menu - see
    # test_second_message_attaches_and_acknowledges for why.
    payloads = {row[0]["payload"] for row in _fake_send[0]["buttons"]}
    assert payloads == {f"close:{ticket.id}"}


# --- client-initiated close -------------------------------------------------------


def test_close_callback_chains_new_ticket_all_the_way_to_closed(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "18"
    db.commit()
    telegram_channel.handle_update(db, _text_update(user_id=18, chat_id=18, text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    assert TicketStatus(ticket.status) == TicketStatus.NEW

    telegram_channel.handle_update(db, _callback_update(user_id=18, chat_id=18, payload=f"close:{ticket.id}"))

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.CLOSED
    assert ticket.csat_requested_at is not None


def test_close_callback_on_already_closed_ticket_is_a_no_op(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "19"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    telegram_channel.handle_update(db, _callback_update(user_id=19, chat_id=19, payload=f"close:{ticket.id}"))
    assert any("уже закрыта" in s["text"] for s in _fake_send)


# --- notifications -------------------------------------------------------


def test_transition_status_notifies_client(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "20"
    db.commit()
    telegram_channel.handle_update(db, _text_update(user_id=20, chat_id=20, text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()

    _fake_send.clear()
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    assert any("изменён: в работе" in s["text"] for s in _fake_send)


def test_notify_assignment_change_sends_engineer_name(db: Session, telegram_enabled, contact: Contact, engineer_user, _fake_send):
    contact.telegram_id = "21"
    db.commit()
    telegram_channel.handle_update(db, _text_update(user_id=21, chat_id=21, text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()

    _fake_send.clear()
    from app.schemas.ticket import TicketUpdate

    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer_user.id), actor=None)

    assert any(engineer_user.full_name in s["text"] for s in _fake_send)


def test_request_csat_sends_rating_buttons(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "22"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    telegram_channel.handle_update(db, _text_update(user_id=22, chat_id=22, text="Привет"))

    telegram_channel.request_csat(db, ticket)
    db.refresh(ticket)
    assert ticket.csat_requested_at is not None
    assert any(s["buttons"] for s in _fake_send)


def test_csat_callback_records_rating_once(db: Session, telegram_enabled, contact: Contact, _fake_send):
    contact.telegram_id = "23"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)

    telegram_channel.handle_update(db, _callback_update(user_id=23, chat_id=23, payload=f"csat:{ticket.id}:4"))
    db.refresh(ticket)
    assert ticket.csat_rating == 4

    telegram_channel.handle_update(db, _callback_update(user_id=23, chat_id=23, payload=f"csat:{ticket.id}:1"))
    db.refresh(ticket)
    assert ticket.csat_rating == 4


def test_try_send_outbound_without_known_chat_does_not_raise(db: Session, telegram_enabled, contact: Contact):
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.TELEGRAM, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.TELEGRAM, body="Ответ")
    db.add(msg)
    db.commit()
    telegram_channel.try_send_outbound(db, ticket, msg)  # no ChannelConversationState exists - must not raise


# --- cross-channel identity matching ("связать телефон") -------------------------------------------------------


def test_link_phone_merges_when_existing_contact_matches(db: Session, telegram_enabled, contact: Contact, _fake_send):
    from app.models.contact import ContactPhone

    db.add(ContactPhone(contact_id=contact.id, phone="+7 916 123-45-67", is_primary=True))
    db.commit()

    telegram_channel.handle_update(db, _text_update(user_id=30, chat_id=30, text="Проблема с 1С"))
    new_contact = db.query(Contact).filter(Contact.telegram_id == "30").first()
    assert new_contact.id != contact.id
    ticket = db.query(Ticket).filter(Ticket.contact_id == new_contact.id).first()

    telegram_channel.handle_update(db, _text_update(user_id=30, chat_id=30, text="связать телефон"))
    telegram_channel.handle_update(db, _text_update(user_id=30, chat_id=30, text="89161234567"))

    assert db.get(Contact, new_contact.id) is None
    db.refresh(ticket)
    assert ticket.contact_id == contact.id
    db.refresh(contact)
    assert contact.telegram_id == "30"
    assert any("объединены" in s["text"] for s in _fake_send)


def test_link_phone_saves_number_when_no_match(db: Session, telegram_enabled, _fake_send):
    telegram_channel.handle_update(db, _text_update(user_id=31, chat_id=31, text="Проблема"))
    contact = db.query(Contact).filter(Contact.telegram_id == "31").first()

    telegram_channel.handle_update(db, _text_update(user_id=31, chat_id=31, text="связать телефон"))
    telegram_channel.handle_update(db, _text_update(user_id=31, chat_id=31, text="+7 999 000-00-00"))

    db.refresh(contact)
    assert len(contact.phones) == 1
    assert any("сохранили номер" in s["text"] for s in _fake_send)
