"""Stage 4 email channel tests: MIME parsing, sender/thread resolution rules
from section 2 (склейка диалога), end-to-end ingestion, and the integration
settings store (secrets never round-trip in plaintext through the API)."""

import smtplib
from email.message import EmailMessage

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.models.contact import Contact, ContactEmail
from app.models.message import Message
from app.models.organization import Organization, OrganizationEmailDomain
from app.models.ticket import Ticket
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.services import email_channel, integration_settings
from app.services import tickets as tickets_service
from app.schemas.ticket import TicketCreate


def _raw_email(
    from_addr="client@example-corp.ru",
    from_name="Иван Клиент",
    to_addr="support@o-horizons.com",
    subject="Не работает 1С",
    body="Здравствуйте, ошибка при входе.",
    message_id=None,
    in_reply_to=None,
    references=None,
    attachment: tuple[str, bytes, str] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    msg.set_content(body)
    if attachment:
        filename, content, mime = attachment
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return bytes(msg)


# --- extract_ticket_tag -------------------------------------------------------


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("Re: Не работает 1С [#OH-1042]", 1042),
        ("[#OH-7]", 7),
        ("Не работает 1С", None),
        ("Re: [OH-1042]", None),  # missing the leading '#' - not our tag format
        ("", None),
    ],
)
def test_extract_ticket_tag(subject, expected):
    assert email_channel.extract_ticket_tag(subject) == expected


# --- parse_message -------------------------------------------------------


def test_parse_message_extracts_fields_and_attachment():
    raw = _raw_email(
        message_id="<abc123@client>",
        in_reply_to="<prev@oh>",
        references=["<root@oh>", "<prev@oh>"],
        attachment=("screenshot.png", b"\x89PNG\r\n\x1a\ndata", "image/png"),
    )
    parsed = email_channel.parse_message(raw)

    assert parsed.from_email == "client@example-corp.ru"
    assert parsed.from_name == "Иван Клиент"
    assert parsed.subject == "Не работает 1С"
    assert "ошибка при входе" in parsed.text_body
    assert parsed.message_id == "<abc123@client>"
    assert parsed.in_reply_to == "<prev@oh>"
    assert parsed.references == ["<root@oh>", "<prev@oh>"]
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].filename == "screenshot.png"
    assert parsed.attachments[0].mime_type == "image/png"
    assert parsed.attachments[0].content.startswith(b"\x89PNG")


def test_parse_message_without_attachment_or_threading():
    raw = _raw_email()
    parsed = email_channel.parse_message(raw)
    assert parsed.attachments == []
    assert parsed.message_id is None
    assert parsed.in_reply_to is None
    assert parsed.references == []


# --- resolve_sender -------------------------------------------------------


def test_resolve_sender_exact_contact_match(db: Session, contact: Contact):
    db.add(ContactEmail(contact_id=contact.id, email="known@example-corp.ru", is_primary=True))
    db.commit()

    parsed = email_channel.parse_message(_raw_email(from_addr="known@example-corp.ru"))
    resolved, created = email_channel.resolve_sender(db, parsed)

    assert resolved.id == contact.id
    assert created is False


def test_resolve_sender_corporate_domain_autolinks_unconfirmed(db: Session, organization: Organization):
    db.add(OrganizationEmailDomain(organization_id=organization.id, domain="example-corp.ru"))
    db.commit()

    parsed = email_channel.parse_message(_raw_email(from_addr="new.person@example-corp.ru", from_name="Новый Сотрудник"))
    resolved, created = email_channel.resolve_sender(db, parsed)

    assert created is True
    assert resolved.organization_id == organization.id
    assert resolved.is_confirmed is False
    assert resolved.full_name == "Новый Сотрудник"


def test_resolve_sender_unregistered_domain_goes_to_unknown_queue(db: Session):
    parsed = email_channel.parse_message(_raw_email(from_addr="someone@totally-unregistered-domain.test"))
    resolved, created = email_channel.resolve_sender(db, parsed)

    assert created is True
    assert resolved.is_confirmed is False
    unknown_org = db.get(Organization, resolved.organization_id)
    assert unknown_org.name == email_channel.UNKNOWN_ORGANIZATION_NAME


def test_resolve_sender_public_domain_goes_to_unknown_queue(db: Session):
    # gmail.com is seeded as a public domain (app/seed.py) - must never
    # auto-link to an organization even if it happens to match nothing else.
    parsed = email_channel.parse_message(_raw_email(from_addr="someone@gmail.com"))
    resolved, _ = email_channel.resolve_sender(db, parsed)
    unknown_org = db.get(Organization, resolved.organization_id)
    assert unknown_org.name == email_channel.UNKNOWN_ORGANIZATION_NAME


def test_resolve_sender_reuses_unknown_organization_singleton(db: Session):
    parsed_a = email_channel.parse_message(_raw_email(from_addr="a@unregistered-one.test"))
    parsed_b = email_channel.parse_message(_raw_email(from_addr="b@unregistered-two.test"))
    contact_a, _ = email_channel.resolve_sender(db, parsed_a)
    contact_b, _ = email_channel.resolve_sender(db, parsed_b)
    assert contact_a.organization_id == contact_b.organization_id


# --- find_or_create_ticket -------------------------------------------------------


def _open_ticket(db: Session, contact: Contact, subject="Заявка") -> Ticket:
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.EMAIL,
        subject=subject,
        manual_priority=Priority.P3,
        manual_priority_reason="test",
    )
    return tickets_service.create_ticket(db, payload, actor=None)


def test_find_ticket_by_thread_header_wins_over_everything(db: Session, contact: Contact):
    ticket = _open_ticket(db, contact)
    other_ticket = _open_ticket(db, contact)  # a second open ticket that would otherwise be ambiguous
    msg = Message(
        ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.EMAIL,
        body="Ответ", email_message_id="<engineer-reply@oh>",
    )
    db.add(msg)
    db.commit()

    parsed = email_channel.parse_message(_raw_email(in_reply_to="<engineer-reply@oh>"))
    resolved, created, ambiguous = email_channel.find_or_create_ticket(db, contact, parsed)

    assert resolved.id == ticket.id
    assert resolved.id != other_ticket.id
    assert created is False
    assert ambiguous is False


def test_find_ticket_by_subject_tag(db: Session, contact: Contact):
    ticket = _open_ticket(db, contact)
    _open_ticket(db, contact)  # another open ticket - tag must still win

    parsed = email_channel.parse_message(_raw_email(subject=f"Re: что-то [#{ticket.display_number}]"))
    resolved, created, ambiguous = email_channel.find_or_create_ticket(db, contact, parsed)

    assert resolved.id == ticket.id
    assert created is False
    assert ambiguous is False


def test_find_ticket_single_open_ticket(db: Session, contact: Contact):
    ticket = _open_ticket(db, contact)
    parsed = email_channel.parse_message(_raw_email(subject="Продолжение без тега"))
    resolved, created, ambiguous = email_channel.find_or_create_ticket(db, contact, parsed)
    assert resolved.id == ticket.id
    assert created is False
    assert ambiguous is False


def test_find_ticket_multiple_open_tickets_falls_back_ambiguous(db: Session, contact: Contact):
    _open_ticket(db, contact)
    newest = _open_ticket(db, contact)

    parsed = email_channel.parse_message(_raw_email(subject="Без тега и без treading"))
    resolved, created, ambiguous = email_channel.find_or_create_ticket(db, contact, parsed)

    assert resolved.id == newest.id  # most recently active
    assert created is False
    assert ambiguous is True


def test_find_ticket_no_open_tickets_creates_new(db: Session, contact: Contact):
    parsed = email_channel.parse_message(_raw_email(subject="Совсем новая проблема"))
    resolved, created, ambiguous = email_channel.find_or_create_ticket(db, contact, parsed)

    assert created is True
    assert ambiguous is False
    assert resolved.subject == "Совсем новая проблема"
    assert resolved.channel == Channel.EMAIL
    assert resolved.priority == Priority.P3
    assert resolved.priority_override_reason


def test_find_ticket_ignores_closed_tickets_for_single_open_rule(db: Session, contact: Contact):
    closed = _open_ticket(db, contact)
    tickets_service.transition_status(db, closed, TicketStatus.CANCELLED, actor=None)

    parsed = email_channel.parse_message(_raw_email(subject="Новое обращение"))
    resolved, created, ambiguous = email_channel.find_or_create_ticket(db, contact, parsed)
    assert created is True  # the cancelled ticket doesn't count as "open"


# --- ingest_email (end to end) -------------------------------------------------------


def test_ingest_email_creates_message_and_attachment(db: Session, contact: Contact, tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "attachments_dir", str(tmp_path))
    db.add(ContactEmail(contact_id=contact.id, email="client@example-corp.ru", is_primary=True))
    db.commit()

    raw = _raw_email(
        from_addr="client@example-corp.ru",
        subject="Не открывается база",
        body="Подробности ошибки",
        attachment=("log.txt", b"error trace", "text/plain"),
    )
    result = email_channel.ingest_email(db, raw)

    assert result.ticket_created is True
    assert result.contact_created is False
    assert result.ambiguous is False
    assert result.message.direction == MessageDirection.INBOUND
    assert result.message.channel == Channel.EMAIL
    assert result.message.body == "Подробности ошибки"
    assert len(result.message.attachments) == 1
    assert result.message.attachments[0].filename == "log.txt"


def test_ingest_email_ambiguous_adds_dispatcher_note(db: Session, contact: Contact):
    db.add(ContactEmail(contact_id=contact.id, email="client@example-corp.ru", is_primary=True))
    db.commit()
    _open_ticket(db, contact)
    _open_ticket(db, contact)

    raw = _raw_email(from_addr="client@example-corp.ru", subject="Ещё один вопрос без тега")
    result = email_channel.ingest_email(db, raw)

    assert result.ambiguous is True
    notes = (
        db.query(Message)
        .filter(Message.ticket_id == result.ticket.id, Message.direction == MessageDirection.INTERNAL_NOTE)
        .all()
    )
    assert len(notes) == 1
    assert "диспетчер" in notes[0].body.lower()


# --- send_outbound_email header/threading logic (SMTP itself is faked) -------


class _FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host, port, timeout=30):
        _FakeSMTP.sent.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)


def _config(**overrides) -> email_channel.EmailConfig:
    base = dict(
        imap_host="imap.example.com", imap_port=993, imap_use_ssl=True,
        imap_username="support@o-horizons.com", imap_password="x", imap_folder="INBOX",
        smtp_host="smtp.example.com", smtp_port=587, smtp_use_tls=True,
        smtp_username="support@o-horizons.com", smtp_password="x",
        from_address="support@o-horizons.com", from_display_name="Открытые Горизонты",
        poll_interval_seconds=30,
    )
    base.update(overrides)
    return email_channel.EmailConfig(**base)


def test_send_outbound_email_tags_subject_and_threads_reply(monkeypatch, contact: Contact, db: Session):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    ticket = _open_ticket(db, contact, subject="Проблема с доступом")

    message_id = email_channel.send_outbound_email(
        _config(), "client@example-corp.ru", ticket, "Проверьте, пожалуйста, сейчас", in_reply_to="<client-msg@example>"
    )

    assert len(_FakeSMTP.sent) == 1
    sent = _FakeSMTP.sent[0]
    assert f"[#{ticket.display_number}]" in sent["Subject"]
    assert sent["Subject"].startswith("Re:")
    assert sent["In-Reply-To"] == "<client-msg@example>"
    assert sent["Message-ID"] == message_id


def test_send_outbound_email_first_send_has_no_re_prefix(monkeypatch, contact: Contact, db: Session):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    ticket = _open_ticket(db, contact, subject="Новый вопрос")

    email_channel.send_outbound_email(_config(), "client@example-corp.ru", ticket, "Здравствуйте", in_reply_to=None)

    sent = _FakeSMTP.sent[0]
    assert not sent["Subject"].startswith("Re:")
    assert f"[#{ticket.display_number}]" in sent["Subject"]


def test_try_send_outbound_without_recipient_does_not_raise(db: Session, contact: Contact):
    ticket = _open_ticket(db, contact)
    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.EMAIL, body="Ответ")
    db.add(msg)
    db.commit()
    email_channel.try_send_outbound(db, ticket, msg, to_address=None)  # must not raise
    assert msg.email_message_id is None


def test_try_send_outbound_without_config_does_not_raise(db: Session, contact: Contact):
    ticket = _open_ticket(db, contact)
    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.EMAIL, body="Ответ")
    db.add(msg)
    db.commit()
    email_channel.try_send_outbound(db, ticket, msg, to_address="client@example-corp.ru")  # no channel configured
    assert msg.email_message_id is None


def test_try_send_outbound_sets_message_id_on_success(monkeypatch, db: Session, contact: Contact):
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    channel_setting = integration_settings.upsert(
        db,
        Channel.EMAIL,
        IntegrationSettingUpdate(
            is_enabled=True,
            config={
                "imap_host": "imap.example.com", "smtp_host": "smtp.example.com",
                "from_address": "support@o-horizons.com",
            },
            secrets={"imap_password": "secret", "smtp_password": "secret"},
        ),
    )
    assert channel_setting.is_enabled is True

    ticket = _open_ticket(db, contact)
    msg = Message(ticket_id=ticket.id, direction=MessageDirection.OUTBOUND, channel=Channel.EMAIL, body="Ответ клиенту")
    db.add(msg)
    db.commit()

    email_channel.try_send_outbound(db, ticket, msg, to_address="client@example-corp.ru")
    db.refresh(msg)
    assert msg.email_message_id is not None
    assert len(_FakeSMTP.sent) == 1


# --- integration_settings service -------------------------------------------------------


def test_integration_settings_secrets_never_round_trip_plaintext(db: Session):
    integration_settings.upsert(
        db,
        Channel.TELEGRAM,
        IntegrationSettingUpdate(is_enabled=True, config={"bot_username": "oh_support_bot"}, secrets={"bot_token": "123:ABC"}),
    )
    setting = integration_settings.get(db, Channel.TELEGRAM)
    read = integration_settings.to_read(setting)

    assert read.secret_keys_set == ["bot_token"]
    assert "123:ABC" not in str(read.model_dump())
    assert integration_settings.decrypt_secret(setting, "bot_token") == "123:ABC"


def test_integration_settings_clearing_secret(db: Session):
    setting = integration_settings.upsert(
        db, Channel.MAX, IntegrationSettingUpdate(secrets={"api_key": "value"})
    )
    assert integration_settings.to_read(setting).secret_keys_set == ["api_key"]

    setting = integration_settings.upsert(db, Channel.MAX, IntegrationSettingUpdate(secrets={"api_key": None}))
    assert integration_settings.to_read(setting).secret_keys_set == []


def test_integration_settings_omitted_secret_key_is_unchanged(db: Session):
    integration_settings.upsert(db, Channel.MAX, IntegrationSettingUpdate(secrets={"api_key": "value"}))
    setting = integration_settings.upsert(db, Channel.MAX, IntegrationSettingUpdate(config={"poll_interval_seconds": 15}))
    assert integration_settings.to_read(setting).secret_keys_set == ["api_key"]
    assert integration_settings.decrypt_secret(setting, "api_key") == "value"
