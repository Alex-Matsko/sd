from app.services import channel_queue
"""Stage 5 MAX channel tests: update parsing, sender/thread resolution rules
mirroring the email channel's, "Мои заявки" ticket switching, explicit
new-ticket creation, and CSAT capture. The MAX HTTP client is always faked -
there is no live bot token in this environment (see docs/decisions.md)."""

import pytest
from pathlib import Path
from datetime import timedelta
from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.channel_conversation_state import ChannelConversationState
from app.models.channel_job import ChannelJob
from app.models.contact import Contact
from app.models.message import Message
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.schemas.message import MessageRead
from app.schemas.ticket import TicketCreate
from app.services import integration_settings, max_channel
from app.services import tickets as tickets_service


@pytest.fixture(autouse=True)
def _fake_send(monkeypatch):
    sent = []

    def _fake(base_url, token, chat_id, text, buttons=None, reply_to_mid=None):
        sent.append({"chat_id": chat_id, "text": text, "buttons": buttons, "reply_to_mid": reply_to_mid})
        return {"message": {"body": {"mid": f"mid.fake.{len(sent)}"}}}

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


def _text_update(user_id="u1", chat_id="c1", text="Привет", name="Клиент MAX", mid=None, reply_mid=None) -> dict:
    message: dict = {
        "sender": {"user_id": user_id, "name": name},
        "recipient": {"chat_id": chat_id},
        "body": {"text": text, "attachments": [], "mid": mid},
    }
    if reply_mid:
        # Real shape confirmed live 2026-07-31 (docs/decisions.md): the
        # original message is nested under link.message.mid, not a flat
        # link.mid.
        message["link"] = {"type": "reply", "message": {"mid": reply_mid, "text": "..."}}
    return {"update_type": "message_created", "message": message}


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


def test_extract_message_created_captures_mid_and_reply_link():
    parsed = max_channel._extract_incoming(_text_update(text="Ответ", mid="mid.111", reply_mid="mid.000"))
    assert parsed.mid == "mid.111"
    assert parsed.reply_to_mid == "mid.000"


def test_extract_link_ignores_forwarded_messages():
    parsed = max_channel._extract_incoming(_text_update(text="Переслано"))
    assert parsed.reply_to_mid is None
    assert max_channel._extract_link_mid({"type": "forward", "mid": "mid.999"}) is None


def test_extract_link_falls_back_to_flat_mid():
    # Defensive fallback only - the confirmed live shape nests under
    # link.message.mid (see _text_update's reply_mid handling).
    assert max_channel._extract_link_mid({"type": "reply", "mid": "mid.flat"}) == "mid.flat"


def _forward_update(text="", forwarded_text="", attachments=None):
    update = _text_update(user_id="forward-client", chat_id="forward-chat", text=text, mid="mid.forward-envelope")
    update["message"]["link"] = {
        "type": "forward", "sender": {"user_id": "original-author"},
        "message": {"mid": "mid.original", "text": forwarded_text, "attachments": attachments or []},
    }
    return update


@pytest.mark.parametrize("own_text,forwarded_text,expected", [
    ("", "", ""), ("", "Пересланный текст", "Пересланный текст"),
    ("Комментарий", "Пересланный текст", "Комментарий\n\nПересланный текст"),
])
def test_extract_forward_preserves_content_and_envelope_identity(own_text, forwarded_text, expected):
    attachment = {"type": "file", "filename": "Документ.pdf", "payload": {"url": "https://files.invalid/document"}}
    parsed = max_channel._extract_incoming(_forward_update(own_text, forwarded_text, [attachment]))
    assert parsed.text == expected
    assert parsed.attachments == [attachment]
    assert parsed.external_user_id == "forward-client"
    assert parsed.mid == "mid.forward-envelope"
    assert parsed.reply_to_mid is None


def test_forward_preserves_direct_attachments_and_handles_null_body():
    forwarded = {"type": "image", "payload": {"url": "https://files.invalid/forwarded"}}
    direct = {"type": "file", "filename": "log.txt", "payload": {"url": "https://files.invalid/direct"}}
    update = _forward_update(attachments=[forwarded])
    update["message"]["body"]["attachments"] = [direct]
    assert max_channel._extract_incoming(update).attachments == [direct, forwarded]
    update["message"]["body"] = None
    assert max_channel._extract_incoming(update).attachments == [forwarded]


def test_reply_does_not_import_quoted_text_or_attachments():
    update = _forward_update(text="Новый ответ", forwarded_text="Старая цитата", attachments=[{"type": "file"}])
    update["message"]["link"]["type"] = "reply"
    parsed = max_channel._extract_incoming(update)
    assert parsed.text == "Новый ответ"
    assert parsed.attachments == []
    assert parsed.reply_to_mid == "mid.original"


@pytest.mark.parametrize("fail_first_download", [False, True])
def test_forwarded_files_are_atomic_visible_and_keep_original_names(db, max_enabled, contact, tmp_path, monkeypatch, _fake_send, fail_first_download):
    monkeypatch.setattr("app.config.settings.attachments_dir", str(tmp_path))
    contact.max_id = "forward-client"
    db.commit()
    ticket = tickets_service.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT,
        channel=Channel.MAX, subject="Пересланные файлы", manual_priority=Priority.P3, manual_priority_reason="test"), actor=None)
    db.add(ChannelConversationState(channel=Channel.MAX, external_user_id="forward-client", chat_id="forward-chat",
                                   contact_id=contact.id, active_ticket_id=ticket.id))
    db.commit()
    contents = {"https://files.invalid/pdf": b"%PDF-test", "https://files.invalid/image": b"\x89PNG\r\n\x1a\ndata"}
    calls = []
    def download(client, url):
        calls.append(url)
        if fail_first_download and len(calls) == 2:
            raise TimeoutError("mock download failure")
        return contents[url]
    monkeypatch.setattr(max_channel.attachments_service, "download_limited", download)
    update = _forward_update(attachments=[
        {"type": "file", "filename": "Документ.pdf", "payload": {"url": "https://files.invalid/pdf"}},
        {"type": "image", "payload": {"url": "https://files.invalid/image"}},
    ])
    job_id = channel_queue.capture_update(db, Channel.MAX, update, max_enabled)
    result = channel_queue.process_inbound(db, *channel_queue.claim(db, "inbound", job_id))
    if fail_first_download:
        assert result is False
        assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0
        assert not [p for p in tmp_path.rglob("*") if p.is_file()]
        assert db.query(ChannelJob).filter(ChannelJob.event_key.like(f"event:{job_id}:reply:%")).count() == 0
        job = db.get(ChannelJob, job_id)
        job.available_at = channel_queue.now() - timedelta(seconds=1)
        db.commit()
        assert channel_queue.process_inbound(db, *channel_queue.claim(db, "inbound", job_id)) is True
    else:
        assert result is True
    message = db.query(Message).filter_by(ticket_id=ticket.id).one()
    visible = MessageRead.model_validate(message)
    assert visible.body == ""
    assert visible.author_contact_id == contact.id
    assert [a.filename for a in visible.attachments] == ["Документ.pdf", "image.png"]
    assert visible.attachments[1].mime_type == "image/png"
    assert [Path(a.stored_path).read_bytes() for a in message.attachments] == list(contents.values())
    assert db.get(ChannelJob, job_id).state == "processed"
    assert channel_queue.claim(db, "inbound", job_id) is None
    assert channel_queue.capture_update(db, Channel.MAX, update, max_enabled) is None
    assert db.query(ChannelJob).filter(ChannelJob.event_key.like(f"event:{job_id}:reply:%")).count() == 1
    assert _fake_send == []  # only a queued acknowledgment, no external sends


# --- bot_started -------------------------------------------------------


def test_bot_started_sends_welcome(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _bot_started_update())
    assert len(_fake_send) == 1
    assert "Открытые Горизонты" in _fake_send[0]["text"] or "поддержки" in _fake_send[0]["text"]


def test_bot_started_sends_main_menu_buttons(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _bot_started_update())
    buttons = _fake_send[0]["buttons"]
    payloads = {row[0]["payload"] for row in buttons}
    assert payloads == {"cmd:my_tickets", "cmd:new_ticket"}


def test_menu_my_tickets_callback_lists_tickets(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-menu1"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, _callback_update(user_id="u-menu1", chat_id="c-menu1", payload="cmd:my_tickets"))
    assert any(s["buttons"] for s in _fake_send)


def test_menu_new_ticket_callback_awaits_description(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _callback_update(user_id="u-menu2", chat_id="c-menu2", payload="cmd:new_ticket"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u-menu2").first()
    assert state.awaiting_new_ticket_text is True


def test_start_command_in_existing_dialog_resends_menu(db: Session, max_enabled, _fake_send):
    # bot_started only fires once ever - a returning client typing "/start"
    # arrives as a plain message_created (verified against a live bot).
    max_channel.handle_update(db, _text_update(user_id="u-menu3", chat_id="c-menu3", text="/start"))
    buttons = _fake_send[-1]["buttons"]
    payloads = {row[0]["payload"] for row in buttons}
    assert payloads == {"cmd:my_tickets", "cmd:new_ticket"}


def test_start_command_cancels_pending_new_ticket_flow(db: Session, max_enabled, _fake_send):
    # Found live: typing "/start" while the bot was waiting for a problem
    # description got swallowed as that description, creating a ticket
    # literally titled "/start" (docs/decisions.md).
    max_channel.handle_update(db, _text_update(user_id="u-cancel1", chat_id="c-cancel1", text="новая заявка"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u-cancel1").first()
    assert state.awaiting_new_ticket_text is True

    max_channel.handle_update(db, _text_update(user_id="u-cancel1", chat_id="c-cancel1", text="/start"))
    db.refresh(state)
    assert state.awaiting_new_ticket_text is False

    contact = db.query(Contact).filter(Contact.max_id == "u-cancel1").first()
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).all() if contact else []
    assert not any(t.subject == "/start" for t in tickets)


def test_my_tickets_command_cancels_pending_revive_flow(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-cancel2"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Старая", manual_priority=Priority.P3, manual_priority_reason="test")
    old_ticket = tickets_service.create_ticket(db, payload, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.CLOSED, actor=None)

    max_channel.handle_update(db, max_channel_callback_for(old_ticket.id, user_id="u-cancel2", chat_id="c-cancel2"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u-cancel2").first()
    assert state.awaiting_revive_text is True

    max_channel.handle_update(db, _text_update(user_id="u-cancel2", chat_id="c-cancel2", text="мои заявки"))
    db.refresh(state)
    assert state.awaiting_revive_text is False
    assert state.revive_parent_ticket_id is None
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).all()
    assert not any(t.subject == "мои заявки" for t in tickets)


def test_ensure_commands_registered_is_memoized_per_token(monkeypatch, max_enabled):
    calls = []
    monkeypatch.setattr(max_channel, "_commands_synced_token", None)
    monkeypatch.setattr(max_channel.max_client, "set_commands", lambda base_url, token, commands: calls.append(token))

    max_channel._ensure_commands_registered(max_enabled)
    max_channel._ensure_commands_registered(max_enabled)

    assert calls == [max_enabled.token]


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
    _fake_send.clear()
    max_channel.handle_update(db, _text_update(user_id="u11", chat_id="c11", text="Второе сообщение"))

    contact = db.query(Contact).filter(Contact.max_id == "u11").first()
    tickets = db.query(Ticket).filter(Ticket.contact_id == contact.id).all()
    assert len(tickets) == 1  # no duplicate ticket created
    messages = db.query(Message).filter(Message.ticket_id == tickets[0].id, Message.direction == MessageDirection.INBOUND).all()
    assert len(messages) == 2

    # Silent gluing used to send nothing back - confusing live testing
    # ("как выйти из диалога, как снова открыть список", docs/decisions.md).
    # Now it acks with the main menu so switching stays discoverable.
    assert len(_fake_send) == 1
    assert tickets[0].display_number in _fake_send[0]["text"]
    payloads = {row[0]["payload"] for row in _fake_send[0]["buttons"]}
    assert payloads == {"cmd:my_tickets", "cmd:new_ticket", f"close:{tickets[0].id}"}


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


def test_multiple_open_tickets_plain_reply_waits_for_explicit_choice(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u13"
    db.commit()
    created_tickets = []
    for subject in ("Заявка А", "Заявка Б"):
        payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject=subject, manual_priority=Priority.P3, manual_priority_reason="test")
        created_tickets.append(tickets_service.create_ticket(db, payload, actor=None))

    max_channel.handle_update(db, _text_update(user_id="u13", chat_id="c13", text="Первое сообщение", mid="mid.choice.first"))
    # Client answers with plain text instead of pressing a button.
    max_channel.handle_update(db, _text_update(user_id="u13", chat_id="c13", text="Это про первую проблему", mid="mid.choice.second"))

    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u13").first()
    assert state.awaiting_ticket_choice is True
    assert state.active_ticket_id is None
    from app.models.channel_job import ChannelJob
    assert db.query(ChannelJob).filter_by(channel='max', state='waiting').count() == 2
    assert db.query(Message).filter(Message.ticket_id.in_([t.id for t in created_tickets])).count() == 0
    chosen = created_tickets[0]
    max_channel.handle_update(db, max_channel_callback_for(chosen.id, user_id="u13", chat_id="c13"))
    assert [m.body for m in db.query(Message).filter_by(ticket_id=chosen.id).order_by(Message.id)] == ["Первое сообщение", "Это про первую проблему"]


def test_my_tickets_command_lists_tickets(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u14"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Не работает 1С", manual_priority=Priority.P3, manual_priority_reason="test")
    tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, _text_update(user_id="u14", chat_id="c14", text="Мои заявки"))

    assert any(s["buttons"] for s in _fake_send)
    button_text = _fake_send[-1]["buttons"][0][0]["text"]
    assert "Не работает 1С" in button_text  # subject visible, not just the number


def test_my_tickets_lists_open_before_closed_with_count(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-order"
    db.commit()
    closed_payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Старая", manual_priority=Priority.P3, manual_priority_reason="test")
    closed = tickets_service.create_ticket(db, closed_payload, actor=None)
    tickets_service.transition_status(db, closed, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, closed, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, closed, TicketStatus.CLOSED, actor=None)

    open_payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Новая", manual_priority=Priority.P3, manual_priority_reason="test")
    open_ticket = tickets_service.create_ticket(db, open_payload, actor=None)

    max_channel.handle_update(db, _text_update(user_id="u-order", chat_id="c-order", text="Мои заявки"))

    last = _fake_send[-1]
    assert "открытых: 1 из 2" in last["text"]
    payloads_in_order = [row[0]["payload"] for row in last["buttons"]]
    assert payloads_in_order == [f"ticket:{open_ticket.id}", f"ticket:{closed.id}"]


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


# --- "поднять старую" (revive a closed/cancelled ticket) -------------------------------------------------------


def test_selecting_closed_ticket_prompts_revive_then_creates_linked_ticket(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-revive"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Старая проблема", manual_priority=Priority.P3, manual_priority_reason="test")
    old_ticket = tickets_service.create_ticket(db, payload, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, old_ticket, TicketStatus.CLOSED, actor=None)

    max_channel.handle_update(db, max_channel_callback_for(old_ticket.id, user_id="u-revive", chat_id="c-revive"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u-revive").first()
    assert state.awaiting_revive_text is True
    assert state.revive_parent_ticket_id == old_ticket.id
    assert state.active_ticket_id is None  # not switched onto the terminal ticket

    max_channel.handle_update(db, _text_update(user_id="u-revive", chat_id="c-revive", text="Проблема повторилась"))
    db.refresh(state)
    assert state.awaiting_revive_text is False
    assert state.revive_parent_ticket_id is None

    new_ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id, Ticket.id != old_ticket.id).first()
    assert new_ticket is not None
    assert new_ticket.parent_ticket_id == old_ticket.id
    assert new_ticket.subject == "Проблема повторилась"
    assert state.active_ticket_id == new_ticket.id


def test_selecting_open_ticket_still_switches_directly(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-open"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Открытая заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)

    max_channel.handle_update(db, max_channel_callback_for(ticket.id, user_id="u-open", chat_id="c-open"))
    state = db.query(ChannelConversationState).filter(ChannelConversationState.external_user_id == "u-open").first()
    assert state.active_ticket_id == ticket.id
    assert state.awaiting_revive_text is False


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
    channel_queue.run_batch(db, "outbound")
    assert ticket.csat_requested_at is not None
    assert any(s["buttons"] and any(button.get("payload", "").startswith("csat:") for row in s["buttons"] for button in row) for s in _fake_send)


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


def test_transition_status_notifies_client_of_new_status(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-notify1"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u-notify1", chat_id="c-notify1", text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()

    channel_queue.run_batch(db, "outbound")
    _fake_send.clear()
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    channel_queue.run_batch(db, "outbound")
    assert any("Статус: В работе" in s["text"] for s in _fake_send)


def test_transition_to_closed_does_not_duplicate_with_csat_message(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-notify2"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u-notify2", chat_id="c-notify2", text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)

    channel_queue.run_batch(db, "outbound")
    _fake_send.clear()
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    # Only the CSAT request goes out, not a second "status changed" message.
    channel_queue.run_batch(db, "outbound")
    assert len(_fake_send) == 1
    assert "закрыта" in _fake_send[0]["text"]


def test_notify_assignment_change_sends_engineer_name(db: Session, max_enabled, contact: Contact, engineer_user, _fake_send):
    contact.max_id = "u-notify3"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u-notify3", chat_id="c-notify3", text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()

    channel_queue.run_batch(db, "outbound")
    _fake_send.clear()
    from app.schemas.ticket import TicketUpdate

    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer_user.id), actor=None)

    channel_queue.run_batch(db, "outbound")
    assert any(engineer_user.full_name in s["text"] for s in _fake_send)


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

    channel_queue.run_batch(db, "outbound")
    _fake_send.clear()
    max_channel.try_send_outbound(db, ticket, msg)
    channel_queue.run_batch(db, "outbound")
    channel_queue.run_batch(db, "outbound")
    assert len(_fake_send) == 1
    assert _fake_send[0]["chat_id"] == "c20"
    assert _fake_send[0]["text"] == f"Заявка {ticket.display_number} — {ticket.subject}\n\nОтвет инженера"
    # Menu buttons ride along on every engineer reply - the /me/commands
    # menu isn't visible on every MAX client (docs/decisions.md).
    payloads = {row[0]["payload"] for row in _fake_send[0]["buttons"]}
    assert payloads == {"cmd:my_tickets", "cmd:new_ticket", f"close:{ticket.id}", f"reply:{ticket.id}"}


def test_inbound_reply_resolves_to_local_message(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _text_update(user_id="u-reply1", chat_id="c-reply1", text="Первое сообщение", mid="mid.first"))
    contact = db.query(Contact).filter(Contact.max_id == "u-reply1").first()
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    first_message = db.query(Message).filter(Message.ticket_id == ticket.id).first()
    assert first_message.max_message_id == "mid.first"

    max_channel.handle_update(
        db,
        _text_update(user_id="u-reply1", chat_id="c-reply1", text="Ответ на первое", mid="mid.second", reply_mid="mid.first"),
    )
    second_message = db.query(Message).filter(Message.ticket_id == ticket.id).order_by(Message.id.desc()).first()
    assert second_message.max_message_id == "mid.second"
    assert second_message.reply_to_message_id == first_message.id


def test_try_send_outbound_with_reply_passes_parent_mid_and_stores_own_mid(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u21"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u21", chat_id="c21", text="Привет", mid="mid.client1"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    inbound = db.query(Message).filter(Message.ticket_id == ticket.id).first()

    reply = Message(
        ticket_id=ticket.id,
        direction=MessageDirection.OUTBOUND,
        channel=Channel.MAX,
        body="Уточните версию",
        reply_to_message_id=inbound.id,
    )
    db.add(reply)
    db.commit()

    channel_queue.run_batch(db, "outbound")
    _fake_send.clear()
    max_channel.try_send_outbound(db, ticket, reply)
    channel_queue.run_batch(db, "outbound")
    channel_queue.run_batch(db, "outbound")
    assert len(_fake_send) == 1
    assert _fake_send[0]["reply_to_mid"] == "mid.client1"
    db.refresh(reply)
    assert reply.max_message_id is not None


def test_try_send_outbound_without_known_chat_does_not_raise(db: Session, max_enabled, contact: Contact):
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.MAX, body="Ответ")
    db.add(msg)
    db.commit()
    max_channel.try_send_outbound(db, ticket, msg)  # no ChannelConversationState exists - must not raise
    channel_queue.run_batch(db, "outbound")


# --- client-initiated close ("Закрыть заявку") -------------------------------------------------------


def test_menu_buttons_offer_close_only_for_closeable_tickets(db: Session, contact: Contact):
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)

    payloads = {row[0]["payload"] for row in max_channel._menu_buttons_for(ticket)}
    assert f"close:{ticket.id}" in payloads

    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    payloads = {row[0]["payload"] for row in max_channel._menu_buttons_for(ticket)}
    assert f"close:{ticket.id}" in payloads  # RESOLVED isn't in OPEN_TICKET_STATUSES but is still closeable

    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)
    payloads = {row[0]["payload"] for row in max_channel._menu_buttons_for(ticket)}
    assert f"close:{ticket.id}" not in payloads

    assert max_channel._menu_buttons_for(None) == max_channel._main_menu_buttons()


def test_close_callback_chains_new_ticket_all_the_way_to_closed(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-close1"
    db.commit()
    max_channel.handle_update(db, _text_update(user_id="u-close1", chat_id="c-close1", text="Проблема"))
    ticket = db.query(Ticket).filter(Ticket.contact_id == contact.id).first()
    assert TicketStatus(ticket.status) == TicketStatus.NEW

    max_channel.handle_update(db, _callback_update(user_id="u-close1", chat_id="c-close1", payload=f"close:{ticket.id}"))

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.CLOSED
    assert ticket.resolved_at is not None
    assert ticket.closed_at is not None
    assert ticket.csat_requested_at is not None  # request_csat fires on the final hop, same as a staff-driven close


def test_close_callback_on_already_closed_ticket_is_a_no_op(db: Session, max_enabled, contact: Contact, _fake_send):
    contact.max_id = "u-close2"
    db.commit()
    payload = TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.MAX, subject="Заявка", manual_priority=Priority.P3, manual_priority_reason="test")
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    max_channel.handle_update(db, _callback_update(user_id="u-close2", chat_id="c-close2", payload=f"close:{ticket.id}"))

    assert any("уже закрыта" in s["text"] for s in _fake_send)


# --- cross-channel identity matching ("связать телефон") -------------------------------------------------------


def test_link_phone_merges_when_existing_contact_matches(db: Session, max_enabled, contact: Contact, _fake_send):
    from app.models.contact import ContactPhone

    contact.full_name = "Известный клиент"
    db.add(ContactPhone(contact_id=contact.id, phone="+7 916 123-45-67", is_primary=True))
    db.commit()

    max_channel.handle_update(db, _text_update(user_id="u-link1", chat_id="c-link1", text="Проблема с 1С"))
    new_contact = db.query(Contact).filter(Contact.max_id == "u-link1").first()
    assert new_contact.id != contact.id
    ticket = db.query(Ticket).filter(Ticket.contact_id == new_contact.id).first()

    max_channel.handle_update(db, _text_update(user_id="u-link1", chat_id="c-link1", text="связать телефон"))
    max_channel.handle_update(db, _text_update(user_id="u-link1", chat_id="c-link1", text="89161234567"))

    assert db.get(Contact, new_contact.id) is None  # merged away
    db.refresh(ticket)
    assert ticket.contact_id == contact.id
    db.refresh(contact)
    assert contact.max_id == "u-link1"
    assert any("объединены" in s["text"] for s in _fake_send)


def test_link_phone_saves_number_when_no_match(db: Session, max_enabled, _fake_send):
    max_channel.handle_update(db, _text_update(user_id="u-link2", chat_id="c-link2", text="Проблема"))
    contact = db.query(Contact).filter(Contact.max_id == "u-link2").first()

    max_channel.handle_update(db, _text_update(user_id="u-link2", chat_id="c-link2", text="связать телефон"))
    max_channel.handle_update(db, _text_update(user_id="u-link2", chat_id="c-link2", text="+7 999 000-00-00"))

    db.refresh(contact)
    assert len(contact.phones) == 1
    assert any("сохранили номер" in s["text"] for s in _fake_send)
