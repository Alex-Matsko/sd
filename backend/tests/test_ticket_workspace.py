"""Archive navigation and customer-visible plans preserve access, SLA and billing."""
from datetime import datetime, timezone
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from app.api.deps import get_current_user
from app.api.routers.portal import get_current_contact
from app.api.routers.tickets import list_tickets
from app.core.enums import Channel, Priority, TicketStatus, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.message import Message
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import tickets

@pytest.fixture()
def admin(db):
    return db.query(User).filter(User.role == UserRole.ADMIN).first()

def make(db, contact, status=TicketStatus.NEW):
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT,
        channel=Channel.PORTAL, subject='План работ по заявке', manual_priority=Priority.P3,
        manual_priority_reason='test'), actor=None)
    ticket.status = status
    ticket.assigned_engineer_id = None
    ticket.team_id = None
    db.commit(); return ticket

@pytest.mark.parametrize('scope,expected', [('active', {'new','resolved'}),('archived', {'closed','cancelled'}),('all', {'new','resolved','closed','cancelled'})])
def test_scope_filters_before_pagination_without_removing_resolved(db, contact, admin, scope, expected):
    created = [make(db, contact, TicketStatus(s)) for s in ['new','resolved','closed','cancelled']]
    response=Response()
    result=list_tickets(response,scope=scope,organization_id=contact.organization_id,limit=1,db=db,actor=admin)
    assert len(result)==1
    assert int(response.headers['X-Total-Count'])==len(expected)
    all_rows=list_tickets(Response(),scope=scope,organization_id=contact.organization_id,db=db,actor=admin)
    assert {t.status.value for t in all_rows}==expected
    assert len(created)==4

def test_legacy_api_still_lists_archived_and_archive_respects_visibility(db, contact, admin, engineer_user):
    mine=make(db,contact,TicketStatus.CLOSED);other=make(db,contact,TicketStatus.CLOSED)
    mine.assigned_engineer_id=engineer_user.id;other.assigned_engineer_id=admin.id;db.commit()
    legacy=list_tickets(Response(),organization_id=contact.organization_id,db=db,actor=admin)
    assert {t.id for t in legacy}=={mine.id,other.id}
    archive=list_tickets(Response(),scope='archived',organization_id=contact.organization_id,db=db,actor=engineer_user)
    assert [t.id for t in archive]==[mine.id]

def test_plan_updates_are_audited_clearable_and_do_not_change_sla_or_log_work(db, contact, admin):
    ticket=make(db,contact)
    sla=(ticket.sla_reaction_due_at,ticket.sla_resolution_due_at)
    due=datetime(2026,12,1,12,30,tzinfo=timezone.utc)
    tickets.update_ticket(db,ticket,TicketUpdate(planned_due_at=due,estimated_minutes=90),admin)
    assert ticket.planned_due_at==due and ticket.estimated_minutes==90
    assert (ticket.sla_reaction_due_at,ticket.sla_resolution_due_at)==sla
    assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).count()==0
    assert db.query(Message).filter_by(ticket_id=ticket.id).count()==0
    audit=db.query(AuditLog).filter_by(entity_type='ticket',entity_id=ticket.id,action='updated').first()
    assert audit.changes['estimated_minutes']['to']==90 and audit.changes['planned_due_at']['to']==due.isoformat()
    tickets.update_ticket(db,ticket,TicketUpdate(is_recurring_problem=True),admin)
    assert ticket.estimated_minutes==90
    tickets.update_ticket(db,ticket,TicketUpdate(planned_due_at=None,estimated_minutes=None),admin)
    assert ticket.planned_due_at is None and ticket.estimated_minutes is None

@pytest.mark.parametrize('payload',[{'estimated_minutes':-1},{'estimated_minutes':600001},{'planned_due_at':'2026-12-01T12:00:00'}])
def test_invalid_plan_rejected(payload):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):TicketUpdate(**payload)

def test_customer_sees_plan_but_cannot_change_it_or_read_other_customer_ticket(db, contact, admin, organization):
    from app.models.contact import Contact
    ticket=make(db,contact)
    ticket.estimated_minutes=150;ticket.planned_due_at=datetime(2026,12,1,tzinfo=timezone.utc);db.commit()
    other=Contact(full_name='Другой клиент',organization_id=organization.id);db.add(other);db.commit()
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_contact]=lambda:contact
    try:
        with TestClient(app) as client:
            r=client.get(f'/portal/tickets/{ticket.id}');assert r.status_code==200
            assert r.json()['estimated_minutes']==150 and r.json()['planned_due_at'].startswith('2026-12-01')
            assert client.patch(f'/tickets/{ticket.id}',json={'estimated_minutes':1}).status_code==401
            app.dependency_overrides[get_current_contact]=lambda:other
            assert client.get(f'/portal/tickets/{ticket.id}').status_code==404
    finally:app.dependency_overrides.clear()

def test_messenger_plan_is_visible_when_opened_without_converting_hours_to_money(db, contact):
    from app.services.messenger_common import planning_summary
    ticket=make(db,contact)
    assert planning_summary(ticket)==''
    ticket.estimated_minutes=150;ticket.planned_due_at=datetime(2026,12,1,9,tzinfo=timezone.utc)
    text=planning_summary(ticket)
    assert '2 ч 30 мин' in text and '01.12.2026 09:00 UTC' in text
    assert '₽' not in text and 'стоимость' not in text.lower()
