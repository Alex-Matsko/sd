"""Email channel (section 2.3): IMAP polling for inbound mail, SMTP for
outbound replies, and the thread-attachment rules from the omnichannel spec
(section 2, "Склейка диалога").

Connection settings live in `integration_settings` (Настройки → Каналы), not
`.env` - see services/integration_settings.py. This module only reads that
config; it never touches app.config directly for credentials.
"""

import imaplib
import logging
import re
import smtplib
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage as StdEmailMessage
from email.parser import BytesParser
from email.utils import make_msgid, parseaddr

from sqlalchemy.orm import Session

from app.core.enums import (
    Channel,
    MessageDirection,
    OPEN_TICKET_STATUSES,
    Priority,
    TicketType,
)
from app.models.contact import Contact, ContactEmail
from app.models.message import Message
from app.models.organization import Organization, OrganizationEmailDomain, PublicEmailDomain
from app.models.ticket import Ticket
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import attachments as attachments_service
from app.services import integration_settings
from app.services import messages as messages_service
from app.services import tickets as tickets_service
from app.services.unknown_queue import UNKNOWN_ORGANIZATION_NAME, get_or_create_unknown_organization

logger = logging.getLogger("app.email_channel")

TICKET_TAG_RE = re.compile(r"\[#OH-(\d+)\]", re.IGNORECASE)


@dataclass
class EmailConfig:
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    imap_username: str
    imap_password: str
    imap_folder: str
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    smtp_username: str
    smtp_password: str
    from_address: str
    from_display_name: str
    poll_interval_seconds: int


@dataclass
class ParsedAttachment:
    filename: str
    content: bytes
    mime_type: str | None


@dataclass
class ParsedEmail:
    from_email: str
    from_name: str
    subject: str
    text_body: str
    message_id: str | None
    in_reply_to: str | None
    references: list[str] = field(default_factory=list)
    attachments: list[ParsedAttachment] = field(default_factory=list)


@dataclass
class IngestResult:
    ticket: Ticket
    message: Message
    ticket_created: bool
    contact_created: bool
    ambiguous: bool


def load_email_config(db: Session) -> EmailConfig | None:
    setting = integration_settings.get(db, Channel.EMAIL)
    if setting is None or not setting.is_enabled:
        return None
    cfg = setting.config or {}
    if not cfg.get("imap_host") or not cfg.get("smtp_host") or not cfg.get("from_address"):
        return None
    return EmailConfig(
        imap_host=cfg["imap_host"],
        imap_port=int(cfg.get("imap_port") or 993),
        imap_use_ssl=bool(cfg.get("imap_use_ssl", True)),
        imap_username=cfg.get("imap_username") or "",
        imap_password=integration_settings.decrypt_secret(setting, "imap_password") or "",
        imap_folder=cfg.get("imap_folder") or "INBOX",
        smtp_host=cfg["smtp_host"],
        smtp_port=int(cfg.get("smtp_port") or 587),
        smtp_use_tls=bool(cfg.get("smtp_use_tls", True)),
        smtp_username=cfg.get("smtp_username") or "",
        smtp_password=integration_settings.decrypt_secret(setting, "smtp_password") or "",
        from_address=cfg["from_address"],
        from_display_name=cfg.get("from_display_name") or "Служба поддержки",
        poll_interval_seconds=int(cfg.get("poll_interval_seconds") or 30),
    )


def extract_ticket_tag(subject: str) -> int | None:
    match = TICKET_TAG_RE.search(subject or "")
    return int(match.group(1)) if match else None


def parse_message(raw: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    from_name, from_email = parseaddr(str(msg.get("From", "")))
    subject = str(msg.get("Subject", "")).strip()
    message_id = msg.get("Message-ID")
    in_reply_to = msg.get("In-Reply-To")
    references_raw = str(msg.get("References", "") or "")
    references = references_raw.split() if references_raw else []

    body_part = msg.get_body(preferencelist=("plain", "html"))
    text_body = body_part.get_content().strip() if body_part is not None else ""

    parsed_attachments: list[ParsedAttachment] = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "attachment"
        content = part.get_content()
        if isinstance(content, str):
            content = content.encode("utf-8")
        parsed_attachments.append(ParsedAttachment(filename=filename, content=content, mime_type=part.get_content_type()))

    return ParsedEmail(
        from_email=from_email.strip().lower(),
        from_name=from_name.strip(),
        subject=subject,
        text_body=text_body,
        message_id=str(message_id) if message_id else None,
        in_reply_to=str(in_reply_to) if in_reply_to else None,
        references=references,
        attachments=parsed_attachments,
    )


def resolve_sender(db: Session, parsed: ParsedEmail) -> tuple[Contact, bool]:
    """Returns (contact, created). Priority (section 2.4/2.3): exact contact
    email match; else corporate domain auto-link (contact created unconfirmed);
    else the unknown-senders queue (also unconfirmed)."""
    existing_email = db.query(ContactEmail).filter(ContactEmail.email == parsed.from_email).first()
    if existing_email is not None:
        return existing_email.contact, False

    domain = parsed.from_email.rsplit("@", 1)[-1] if "@" in parsed.from_email else ""
    is_public = domain and db.get(PublicEmailDomain, domain) is not None

    org: Organization | None = None
    if domain and not is_public:
        org_domain = db.query(OrganizationEmailDomain).filter(OrganizationEmailDomain.domain == domain).first()
        if org_domain is not None:
            org = org_domain.organization

    if org is None:
        org = get_or_create_unknown_organization(db)

    display_name = parsed.from_name or (parsed.from_email.split("@")[0] if parsed.from_email else "Неизвестный отправитель")
    contact = Contact(organization_id=org.id, full_name=display_name, is_confirmed=False)
    db.add(contact)
    db.flush()
    if parsed.from_email:
        db.add(ContactEmail(contact_id=contact.id, email=parsed.from_email, is_primary=True))
    return contact, True


def _find_ticket_by_thread_headers(db: Session, parsed: ParsedEmail) -> Ticket | None:
    candidate_ids = [mid for mid in [parsed.in_reply_to, *parsed.references] if mid]
    if not candidate_ids:
        return None
    message = (
        db.query(Message)
        .filter(Message.email_message_id.in_(candidate_ids))
        .order_by(Message.id.desc())
        .first()
    )
    return message.ticket if message is not None else None


def find_or_create_ticket(db: Session, contact: Contact, parsed: ParsedEmail) -> tuple[Ticket, bool, bool]:
    """Returns (ticket, created, ambiguous). Attachment priority (section 2.3):
    In-Reply-To/References thread match, then the [#OH-<n>] subject tag, then
    the contact's single open ticket; multiple open tickets with neither header
    nor tag fall back to the most recently active one, flagged for dispatcher
    review (docs/decisions.md, mirrors the messenger "не ответил боту" rule)."""
    ticket = _find_ticket_by_thread_headers(db, parsed)
    if ticket is not None:
        return ticket, False, False

    tag = extract_ticket_tag(parsed.subject)
    if tag is not None:
        ticket = db.query(Ticket).filter(Ticket.number == tag).first()
        if ticket is not None:
            return ticket, False, False

    open_tickets = (
        db.query(Ticket)
        .filter(Ticket.contact_id == contact.id, Ticket.status.in_(OPEN_TICKET_STATUSES))
        # id as a tiebreaker: Postgres now() is transaction-start time, so two
        # tickets created in the same transaction can share updated_at exactly.
        .order_by(Ticket.updated_at.desc(), Ticket.id.desc())
        .all()
    )
    if len(open_tickets) == 1:
        return open_tickets[0], False, False
    if len(open_tickets) > 1:
        return open_tickets[0], False, True

    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.EMAIL,
        subject=parsed.subject or "(без темы)",
        manual_priority=Priority.P3,
        manual_priority_reason="Автоматически создано по email - приоритет уточняется диспетчером",
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    return ticket, True, False


def ingest_email(db: Session, raw: bytes) -> IngestResult:
    parsed = parse_message(raw)
    contact, contact_created = resolve_sender(db, parsed)
    ticket, ticket_created, ambiguous = find_or_create_ticket(db, contact, parsed)

    message = messages_service.add_message(
        db,
        ticket,
        MessageCreate(direction=MessageDirection.INBOUND, body=parsed.text_body, channel=Channel.EMAIL),
        author_contact=contact,
    )
    message.email_message_id = parsed.message_id
    message.email_in_reply_to = parsed.in_reply_to
    db.add(message)

    for att in parsed.attachments:
        db.add(attachments_service.store_attachment(message.id, att.filename, att.content, att.mime_type))

    if ambiguous:
        messages_service.add_message(
            db,
            ticket,
            MessageCreate(
                direction=MessageDirection.INTERNAL_NOTE,
                body=(
                    f"Автоматически привязано к последней активной заявке — у контакта несколько открытых "
                    f"заявок, письмо от {parsed.from_email} не содержало ссылки на конкретную заявку. "
                    "Уточните у диспетчера/клиента, к какой заявке относится обращение."
                ),
                channel=Channel.EMAIL,
            ),
        )

    db.commit()
    db.refresh(message)
    return IngestResult(
        ticket=ticket, message=message, ticket_created=ticket_created, contact_created=contact_created, ambiguous=ambiguous
    )


def send_outbound_email(config: EmailConfig, to_address: str, ticket: Ticket, body: str, in_reply_to: str | None) -> str:
    msg = StdEmailMessage()
    msg["From"] = f"{config.from_display_name} <{config.from_address}>"
    msg["To"] = to_address
    tag = f"[#{ticket.display_number}]"
    subject = ticket.subject if tag in ticket.subject else f"{ticket.subject} {tag}"
    msg["Subject"] = f"Re: {subject}" if in_reply_to else subject
    message_id = make_msgid(domain=config.from_address.rsplit("@", 1)[-1])
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
        if config.smtp_use_tls:
            smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password)
        smtp.send_message(msg)

    return message_id


def poll_inbox(db: Session, config: EmailConfig) -> int:
    """One IMAP poll: fetches unseen mail and ingests each. A message is
    considered processed once fetched (RFC822 fetch marks \\Seen), even if
    ingestion then fails - see docs/decisions.md for why v1 accepts "lose a
    malformed message" over "retry it forever and risk partial duplicates"."""
    imap_cls = imaplib.IMAP4_SSL if config.imap_use_ssl else imaplib.IMAP4
    imap = imap_cls(config.imap_host, config.imap_port)
    try:
        imap.login(config.imap_username, config.imap_password)
        imap.select(config.imap_folder)
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return 0
        ids = data[0].split()
        processed = 0
        for msg_num in ids:
            try:
                fetch_status, msg_data = imap.fetch(msg_num, "(RFC822)")
                if fetch_status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                ingest_email(db, raw)
                processed += 1
            except Exception:
                logger.exception("Не удалось обработать входящее письмо (IMAP id=%s)", msg_num)
        return processed
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()


def try_send_outbound(db: Session, ticket: Ticket, message: Message, to_address: str | None) -> None:
    """Best-effort SMTP send for an engineer's reply on an email-channel ticket.
    Failures are logged, not raised - the reply still exists in the system and
    is visible to the engineer even if delivery to the client failed."""
    if not to_address:
        logger.warning("Заявка %s: у контакта нет email, письмо не отправлено", ticket.display_number)
        return
    config = load_email_config(db)
    if config is None:
        logger.warning("Заявка %s: канал email не настроен, письмо не отправлено", ticket.display_number)
        return
    try:
        last_inbound = (
            db.query(Message)
            .filter(Message.ticket_id == ticket.id, Message.email_message_id.isnot(None))
            .order_by(Message.id.desc())
            .first()
        )
        in_reply_to = last_inbound.email_message_id if last_inbound else None
        sent_message_id = send_outbound_email(config, to_address, ticket, message.body, in_reply_to)
        message.email_message_id = sent_message_id
        db.add(message)
        db.commit()
    except Exception:
        logger.exception("Заявка %s: ошибка отправки письма клиенту", ticket.display_number)
