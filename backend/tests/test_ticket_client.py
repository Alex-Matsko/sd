"""Привязка заявки к организации и контакту (POST /tickets/{id}/client):
прежде всего заявок из бота, чей отправитель попал в «Неизвестные»."""

import pytest

from app.core.enums import Channel, Priority, TicketType
from app.models.audit import AuditLog
from app.models.channel_conversation_state import ChannelConversationState
from app.models.contact import Contact
from app.schemas.ticket import TicketClientChange, TicketCreate
from app.services import tickets as tickets_service
from app.services.unknown_queue import get_or_create_unknown_organization


def _ticket(db, contact, subject="Из бота"):
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id,
            type=TicketType.INCIDENT,
            channel=Channel.TELEGRAM,
            subject=subject,
            manual_priority=Priority.P3,
            manual_priority_reason="фикстура теста",
        ),
        actor=None,
    )


@pytest.fixture()
def bot_contact(db):
    unknown = get_or_create_unknown_organization(db)
    c = Contact(organization_id=unknown.id, full_name="Telegram: Пётр", telegram_id="tg-777", is_confirmed=False)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_человек_из_бота_переносится_в_организацию_со_всеми_заявками(db, bot_contact, organization, active_contract):
    first, second = _ticket(db, bot_contact), _ticket(db, bot_contact, "Второе")
    assert first.has_no_active_contract is True

    tickets_service.change_client(db, first, TicketClientChange(organization_id=organization.id), actor=None)

    db.refresh(bot_contact)
    assert bot_contact.organization_id == organization.id
    for t in (first, second):
        db.refresh(t)
        assert t.organization_id == organization.id
        assert t.contact_id == bot_contact.id
        assert t.contract_id == active_contract.id
        assert t.has_no_active_contract is False
        log = db.query(AuditLog).filter(AuditLog.entity_id == t.id, AuditLog.action == "client_changed").one()
        assert log.changes["organization_id"]["to"] == organization.id


def test_контакт_из_бота_объединяется_с_контактом_организации_и_переписка_не_рвётся(db, bot_contact, contact, organization):
    state = ChannelConversationState(channel=Channel.TELEGRAM, external_user_id="tg-777", chat_id="tg-777", contact_id=bot_contact.id)
    db.add(state)
    db.commit()
    ticket = _ticket(db, bot_contact)
    bot_id = bot_contact.id

    tickets_service.change_client(
        db, ticket, TicketClientChange(organization_id=organization.id, contact_id=contact.id), actor=None
    )

    db.refresh(ticket)
    db.refresh(contact)
    db.refresh(state)
    assert ticket.organization_id == organization.id
    assert ticket.contact_id == contact.id
    # Ответ инженера уходит в бот по контакту заявки: привязка переехала.
    assert contact.telegram_id == "tg-777"
    assert state.contact_id == contact.id
    assert db.get(Contact, bot_id) is None
    log = db.query(AuditLog).filter(AuditLog.entity_id == ticket.id, AuditLog.action == "client_changed").one()
    assert log.changes["contact_id"] == {"from": bot_id, "to": contact.id}


def test_заведённые_контакты_не_объединяются(db, contact, organization):
    other = Contact(organization_id=organization.id, full_name="Другой человек")
    db.add(other)
    db.commit()
    ticket = _ticket(db, contact)
    with pytest.raises(ValueError, match="только контакты из «Неизвестных»"):
        tickets_service.change_client(
            db, ticket, TicketClientChange(organization_id=organization.id, contact_id=other.id), actor=None
        )
    db.refresh(ticket)
    assert ticket.contact_id == contact.id


def test_контакт_должен_быть_из_выбранной_организации(db, bot_contact, contact):
    from app.models.organization import Organization

    elsewhere = Organization(name="Другая")
    db.add(elsewhere)
    db.commit()
    ticket = _ticket(db, bot_contact)
    with pytest.raises(ValueError, match="не из выбранной организации"):
        tickets_service.change_client(
            db, ticket, TicketClientChange(organization_id=elsewhere.id, contact_id=contact.id), actor=None
        )
