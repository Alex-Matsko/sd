"""Client portal (section 7): authentication for a Contact and the queries
that answer "what may this client see".

Every read here is scoped through `visible_tickets_query`. That single choke
point exists on purpose: the portal is the only place where an outsider
touches the data, so "which tickets are mine" must be decided in one function
that is easy to audit, not re-derived in each endpoint.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import MessageDirection
from app.core.security import hash_password, verify_password
from app.models.contact import Contact, ContactEmail
from app.models.message import Message
from app.models.portal_auth import PortalCredential, PortalLoginToken
from app.models.ticket import Ticket

logger = logging.getLogger("app.portal")


class PortalAuthError(Exception):
    pass


def find_contact_by_email(db: Session, email: str) -> Contact | None:
    row = (
        db.query(ContactEmail)
        .filter(ContactEmail.email == email.strip().lower())
        .first()
    )
    return row.contact if row else None


def get_or_create_credential(db: Session, contact: Contact) -> PortalCredential:
    credential = db.query(PortalCredential).filter(PortalCredential.contact_id == contact.id).first()
    if credential is None:
        credential = PortalCredential(contact_id=contact.id)
        db.add(credential)
        db.flush()
    return credential


def set_password(db: Session, contact: Contact, password: str) -> PortalCredential:
    credential = get_or_create_credential(db, contact)
    credential.password_hash = hash_password(password)
    db.add(credential)
    db.commit()
    return credential


def has_access(db: Session, contact: Contact) -> bool:
    credential = db.query(PortalCredential).filter(PortalCredential.contact_id == contact.id).first()
    return credential is not None and bool(credential.password_hash)


def revoke_access(db: Session, contact: Contact) -> None:
    """Отзывает доступ в кабинет.

    Нужно, когда сотрудник клиента уволился: без этого отрезать его было
    нечем — пароль оставался рабочим, а magic-link выдавался по адресу
    почты, который никуда не делся.

    Убирается и пароль, и невыпользованные ссылки для входа: живая ссылка
    из почты — такой же ключ, как пароль.
    """
    credential = db.query(PortalCredential).filter(PortalCredential.contact_id == contact.id).first()
    if credential is not None:
        db.delete(credential)
    db.query(PortalLoginToken).filter(
        PortalLoginToken.contact_id == contact.id, PortalLoginToken.used_at.is_(None)
    ).delete()
    db.commit()


def authenticate_with_password(db: Session, email: str, password: str) -> Contact:
    """Deliberately returns the same error whether the address is unknown or
    the password is wrong - distinguishing them would let anyone enumerate
    which of a client's staff have portal accounts."""
    invalid = PortalAuthError("Неверный email или пароль")
    contact = find_contact_by_email(db, email)
    if contact is None:
        raise invalid
    credential = db.query(PortalCredential).filter(PortalCredential.contact_id == contact.id).first()
    if credential is None or not credential.password_hash:
        raise invalid
    if not verify_password(password, credential.password_hash):
        raise invalid
    credential.last_login_at = datetime.now(timezone.utc)
    db.add(credential)
    db.commit()
    return contact


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_magic_link(db: Session, email: str, ticket_id: int | None = None) -> tuple[Contact, str] | None:
    """Returns (contact, link) or None when the address is unknown.

    The caller must respond identically either way - a different response for
    an unknown address turns this endpoint into a directory of who works at
    the client."""
    contact = find_contact_by_email(db, email)
    if contact is None:
        return None

    raw = secrets.token_urlsafe(32)
    db.add(
        PortalLoginToken(
            contact_id=contact.id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.portal_magic_link_ttl_minutes),
        )
    )
    db.commit()
    from urllib.parse import urlencode
    params = {}
    if ticket_id is not None and get_visible_ticket(db, contact, ticket_id) is not None:
        params["ticket"] = ticket_id
    params["token"] = raw
    return contact, f"{settings.portal_base_url.rstrip('/')}/login?{urlencode(params)}"


def consume_magic_link(db: Session, raw_token: str) -> Contact:
    token = (
        db.query(PortalLoginToken)
        .filter(PortalLoginToken.token_hash == _hash_token(raw_token))
        .first()
    )
    if token is None or token.used_at is not None:
        raise PortalAuthError("Ссылка недействительна или уже использована")
    if token.expires_at < datetime.now(timezone.utc):
        raise PortalAuthError("Срок действия ссылки истёк")

    token.used_at = datetime.now(timezone.utc)
    db.add(token)
    contact = db.get(Contact, token.contact_id)
    if contact is None:
        raise PortalAuthError("Ссылка недействительна или уже использована")
    credential = get_or_create_credential(db, contact)
    credential.last_login_at = datetime.now(timezone.utc)
    db.add(credential)
    db.commit()
    return contact


def visible_tickets_query(db: Session, contact: Contact):
    """The single rule for portal visibility (section 6): a client sees their
    own tickets, or every ticket of their organization when the contact has
    `can_view_org_tickets`. Everything the portal reads goes through here."""
    query = db.query(Ticket)
    if contact.can_view_org_tickets:
        return query.filter(Ticket.organization_id == contact.organization_id)
    return query.filter(Ticket.contact_id == contact.id)


def get_visible_ticket(db: Session, contact: Contact, ticket_id: int) -> Ticket | None:
    return visible_tickets_query(db, contact).filter(Ticket.id == ticket_id).first()


def visible_messages(db: Session, ticket: Ticket) -> list[Message]:
    """Internal notes never reach the portal - they're where engineers write
    things not meant for the client (dispatcher hints, ambiguity warnings
    written by the channel adapters)."""
    return (
        db.query(Message)
        .filter(
            Message.ticket_id == ticket.id,
            or_(
                Message.direction == MessageDirection.INBOUND,
                Message.direction == MessageDirection.OUTBOUND,
            ),
        )
        .order_by(Message.created_at, Message.id)
        .all()
    )
