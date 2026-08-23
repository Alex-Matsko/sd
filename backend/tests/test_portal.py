"""Client portal (ТЗ р. 7, Этап 8).

The portal is the only surface an outsider touches, so most of these tests
are about what a client must *not* be able to reach: another organization's
tickets, a colleague's tickets without the org-wide flag, internal notes, or
the staff API with a portal token."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.core.security import create_portal_access_token, decode_access_token
from app.models.contact import Contact, ContactEmail
from app.models.organization import Organization
from app.models.portal_auth import PortalLoginToken
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import messages as messages_service
from app.services import portal
from app.services import tickets as tickets_service


@pytest.fixture()
def client_contact(db: Session, organization: Organization) -> Contact:
    contact = Contact(organization_id=organization.id, full_name="Клиент Портальный")
    db.add(contact)
    db.flush()
    db.add(ContactEmail(contact_id=contact.id, email="client.portal@example.com", is_primary=True))
    db.commit()
    return contact


def _ticket(db: Session, contact: Contact, subject="Заявка клиента") -> object:
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PORTAL, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )


# --- authentication -------------------------------------------------


def test_password_login_succeeds(db: Session, client_contact: Contact):
    portal.set_password(db, client_contact, "ClientPass123!")
    assert portal.authenticate_with_password(db, "client.portal@example.com", "ClientPass123!").id == client_contact.id


def test_wrong_password_and_unknown_email_fail_identically(db: Session, client_contact: Contact):
    """Different messages would let an outsider enumerate who has an account."""
    portal.set_password(db, client_contact, "ClientPass123!")
    with pytest.raises(portal.PortalAuthError) as wrong:
        portal.authenticate_with_password(db, "client.portal@example.com", "неверный")
    with pytest.raises(portal.PortalAuthError) as unknown:
        portal.authenticate_with_password(db, "never.seen@example.com", "что-нибудь")
    assert str(wrong.value) == str(unknown.value)


def test_contact_without_password_cannot_log_in(db: Session, client_contact: Contact):
    """A contact that has only ever used magic links has no password set -
    that must be a refusal, not a crash or an empty-password bypass."""
    with pytest.raises(portal.PortalAuthError):
        portal.authenticate_with_password(db, "client.portal@example.com", "")


def test_magic_link_round_trip(db: Session, client_contact: Contact):
    result = portal.issue_magic_link(db, "client.portal@example.com")
    assert result is not None
    _, link = result
    token = link.split("token=")[1]
    assert portal.consume_magic_link(db, token).id == client_contact.id


def test_magic_link_is_single_use(db: Session, client_contact: Contact):
    _, link = portal.issue_magic_link(db, "client.portal@example.com")
    token = link.split("token=")[1]
    portal.consume_magic_link(db, token)
    with pytest.raises(portal.PortalAuthError):
        portal.consume_magic_link(db, token)


def test_expired_magic_link_is_rejected(db: Session, client_contact: Contact):
    _, link = portal.issue_magic_link(db, "client.portal@example.com")
    token = link.split("token=")[1]
    stored = db.query(PortalLoginToken).filter(PortalLoginToken.contact_id == client_contact.id).first()
    stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    with pytest.raises(portal.PortalAuthError):
        portal.consume_magic_link(db, token)


def test_magic_link_is_stored_hashed(db: Session, client_contact: Contact):
    """A leaked database row must not be usable as a login."""
    _, link = portal.issue_magic_link(db, "client.portal@example.com")
    raw = link.split("token=")[1]
    stored = db.query(PortalLoginToken).filter(PortalLoginToken.contact_id == client_contact.id).first()
    assert stored.token_hash != raw


def test_magic_link_for_unknown_email_returns_none(db: Session):
    assert portal.issue_magic_link(db, "nobody@example.com") is None


def test_portal_token_is_not_a_staff_token(db: Session, client_contact: Contact):
    """The token type is the boundary between clients and staff: deps
    .get_current_user only accepts type "access"."""
    payload = decode_access_token(create_portal_access_token(client_contact.id))
    assert payload["type"] == "portal"
    assert payload["sub"] == str(client_contact.id)


# --- visibility -------------------------------------------------------


def test_client_sees_only_own_tickets_by_default(db: Session, client_contact: Contact, organization: Organization):
    mine = _ticket(db, client_contact, "Моя заявка")
    colleague = Contact(organization_id=organization.id, full_name="Коллега")
    db.add(colleague)
    db.flush()
    theirs = _ticket(db, colleague, "Заявка коллеги")

    visible = {t.id for t in portal.visible_tickets_query(db, client_contact).all()}
    assert mine.id in visible
    assert theirs.id not in visible


def test_org_wide_flag_reveals_colleagues_tickets(db: Session, client_contact: Contact, organization: Organization):
    colleague = Contact(organization_id=organization.id, full_name="Коллега")
    db.add(colleague)
    db.flush()
    theirs = _ticket(db, colleague, "Заявка коллеги")

    client_contact.can_view_org_tickets = True
    db.commit()

    visible = {t.id for t in portal.visible_tickets_query(db, client_contact).all()}
    assert theirs.id in visible


def test_другая_организация_никогда_не_видна(db: Session, client_contact: Contact):
    """Even with the org-wide flag, visibility stops at the organization."""
    other_org = Organization(name="Другая организация")
    db.add(other_org)
    db.flush()
    stranger = Contact(organization_id=other_org.id, full_name="Чужой контакт")
    db.add(stranger)
    db.flush()
    foreign = _ticket(db, stranger, "Чужая заявка")

    client_contact.can_view_org_tickets = True
    db.commit()

    visible = {t.id for t in portal.visible_tickets_query(db, client_contact).all()}
    assert foreign.id not in visible
    assert portal.get_visible_ticket(db, client_contact, foreign.id) is None


def test_internal_notes_never_reach_the_portal(db: Session, client_contact: Contact, engineer_user):
    ticket = _ticket(db, client_contact)
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Вопрос клиента"), author_contact=client_contact
    )
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Ответ поддержки"), author_user=engineer_user
    )
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INTERNAL_NOTE, body="СЕКРЕТНАЯ ЗАМЕТКА"), author_user=engineer_user
    )

    bodies = [m.body for m in portal.visible_messages(db, ticket)]
    assert "Вопрос клиента" in bodies
    assert "Ответ поддержки" in bodies
    assert "СЕКРЕТНАЯ ЗАМЕТКА" not in bodies


def test_client_reply_reopens_a_resolved_ticket(db: Session, client_contact: Contact):
    """Portal replies go through the same add_message path as every other
    channel, so the section 4.2 reopen rule applies here too."""
    ticket = _ticket(db, client_contact)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)

    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Всё ещё не работает", channel=Channel.PORTAL),
        author_contact=client_contact,
    )
    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.IN_PROGRESS


def test_reply_to_a_closed_ticket_opens_a_linked_one(db: Session, contact: Contact):
    """Раньше сообщение молча ложилось в закрытую заявку: она не
    переоткрывалась, новая не заводилась, никого не уведомляли. Email в этом
    случае заводит новую заявку, боты предлагают «поднять старую» — портал
    вёл себя иначе, чем оба канала."""
    from app.api.routers.portal import reply_to_my_ticket
    from app.core.enums import TicketStatus
    from app.schemas.portal import PortalMessageCreate
    from app.services import tickets as tickets_service
    from app.models.ticket import Ticket

    closed = _ticket(db, contact, "Старая проблема")
    for step in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED):
        tickets_service.transition_status(db, closed, step, actor=None)

    reply_to_my_ticket(
        ticket_id=closed.id,
        payload=PortalMessageCreate(body="Проблема вернулась"),
        contact=contact,
        db=db,
    )

    db.refresh(closed)
    assert TicketStatus(closed.status) == TicketStatus.CLOSED, "закрытая заявка не должна оживать"

    fresh = db.query(Ticket).filter(Ticket.parent_ticket_id == closed.id).one()
    assert fresh.subject == "Проблема вернулась"
    assert [m.body for m in fresh.messages] == ["Проблема вернулась"]


def test_reply_to_an_open_ticket_still_lands_in_it(db: Session, contact: Contact):
    """Обычный случай не должен пострадать: новая заявка заводится только для
    закрытых."""
    from app.api.routers.portal import reply_to_my_ticket
    from app.schemas.portal import PortalMessageCreate
    from app.models.ticket import Ticket

    ticket = _ticket(db, contact, "Текущая проблема")
    before = db.query(Ticket).count()

    reply_to_my_ticket(
        ticket_id=ticket.id, payload=PortalMessageCreate(body="Дополнение"), contact=contact, db=db
    )

    assert db.query(Ticket).count() == before
    db.refresh(ticket)
    assert "Дополнение" in [m.body for m in ticket.messages]
