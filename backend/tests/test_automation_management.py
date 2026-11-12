from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import AutomationTriggerType, Channel, MessageDirection, Priority, TicketStatus, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.automation_rule import AutomationRule
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import automation, messages, settings_audit, tickets


@pytest.fixture()
def api(db):
    actor = db.query(User).filter(User.role == UserRole.ADMIN).first()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    settings_audit.set_actor(db, actor.id)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous


def rule_payload(**overrides):
    return {'name': ' Возврат ожидания в работу ', 'trigger_type': 'status_without_reply',
            'from_status': 'waiting_third_party', 'to_status': 'in_progress', 'threshold_days': 2, **overrides}


def test_create_edit_toggle_and_audit(api, db):
    response = api.post('/automation-rules', json=rule_payload())
    assert response.status_code == 201
    rule = response.json()
    assert rule['name'] == 'Возврат ожидания в работу' and rule['is_active'] is False
    response = api.patch(f"/automation-rules/{rule['id']}", json={'name': 'Проверка ожидания', 'threshold_days': 5,
        'trigger_type': 'status_age', 'from_status': 'waiting_customer', 'to_status': 'cancelled', 'is_active': True})
    assert response.status_code == 200
    assert response.json()['trigger_type'] == 'status_age' and response.json()['threshold_days'] == 5
    assert api.patch(f"/automation-rules/{rule['id']}", json={'is_active': False}).json()['is_active'] is False
    audits = db.query(AuditLog).filter_by(entity_type='automation_rule', entity_id=rule['id']).all()
    assert db.query(AuditLog).filter_by(entity_type='automation_rule', action='created').filter(AuditLog.changes['name'].as_string() == 'Возврат ожидания в работу').first() is not None
    assert any(a.action == 'updated' for a in audits)


@pytest.mark.parametrize('overrides', [
    {'name': '   '}, {'threshold_days': 0}, {'threshold_days': 3651}, {'trigger_type': 'arbitrary_script'},
    {'from_status': 'closed', 'to_status': 'in_progress'}, {'from_status': 'new', 'to_status': 'new'},
    {'from_status': 'waiting_customer', 'to_status': 'closed'},
    {'trigger_type': 'resolved_without_reply', 'from_status': 'waiting_customer'},
])
def test_invalid_conditions_are_rejected(api, overrides):
    assert api.post('/automation-rules', json=rule_payload(**overrides)).status_code == 422


def test_conflicting_active_source_requires_disabling_previous_rule(api, db):
    first = api.post('/automation-rules', json=rule_payload(is_active=True)).json()
    assert 'id' in first
    second = api.post('/automation-rules', json=rule_payload(name='Другой срок', trigger_type='status_age', threshold_days=5)).json()
    assert api.patch(f"/automation-rules/{second['id']}", json={'is_active': True}).status_code == 409
    assert api.post('/automation-rules', json=rule_payload(name='Конфликт', is_active=True)).status_code == 409
    assert api.patch(f"/automation-rules/{first['id']}", json={'is_active': False}).status_code == 200
    assert api.patch(f"/automation-rules/{second['id']}", json={'is_active': True}).status_code == 200
    assert db.query(AutomationRule).filter_by(from_status=TicketStatus.WAITING_THIRD_PARTY, is_active=True).count() == 1
    assert api.patch(f"/automation-rules/{second['id']}", json={'threshold_days': None}).status_code == 422
    assert api.patch(f"/automation-rules/{second['id']}", json={'name': '  '}).status_code == 422


def test_engineer_cannot_create_or_modify(api, engineer_user):
    rule = api.post('/automation-rules', json=rule_payload()).json()
    app.dependency_overrides[get_current_user] = lambda: engineer_user
    assert api.post('/automation-rules', json=rule_payload()).status_code == 403
    assert api.patch(f"/automation-rules/{rule['id']}", json={'is_active': True}).status_code == 403


def old_waiting_ticket(db, contact):
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PORTAL,
        subject='Ожидаем поставщика', manual_priority=Priority.P3, manual_priority_reason='test'), actor=None)
    tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets.transition_status(db, ticket, TicketStatus.WAITING_THIRD_PARTY, actor=None)
    for row in db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='status_changed'):
        row.created_at -= timedelta(days=3)
    db.commit()
    return ticket


def generic_rule(db, trigger):
    for rule in db.query(AutomationRule): rule.is_active = False
    rule = AutomationRule(name='Проверка ожидания', trigger_type=trigger, from_status=TicketStatus.WAITING_THIRD_PARTY,
        to_status=TicketStatus.IN_PROGRESS, threshold_days=2, is_active=True)
    db.add(rule); db.commit()
    return rule


def test_recent_customer_reply_resets_no_reply_timer(db, contact):
    generic_rule(db, AutomationTriggerType.STATUS_WITHOUT_REPLY)
    ticket = old_waiting_ticket(db, contact)
    messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body='Есть уточнение'), author_contact=contact)
    assert automation.run_automation_rules(db) == 0
    db.refresh(ticket); assert ticket.status == TicketStatus.WAITING_THIRD_PARTY


def test_internal_note_does_not_reset_customer_reply_timer_and_rule_is_audited(db, contact):
    rule = generic_rule(db, AutomationTriggerType.STATUS_WITHOUT_REPLY)
    ticket = old_waiting_ticket(db, contact)
    messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.INTERNAL_NOTE, body='Проверяем'))
    assert automation.run_automation_rules(db) == 1
    db.refresh(ticket); assert ticket.status == TicketStatus.IN_PROGRESS
    audit = db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='automation_applied').one()
    assert audit.changes['rule_id'] == rule.id
    assert automation.run_automation_rules(db) == 0


def test_time_in_status_does_not_reset_on_messages(db, contact):
    generic_rule(db, AutomationTriggerType.STATUS_AGE)
    ticket = old_waiting_ticket(db, contact)
    messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body='Новое сообщение'), author_contact=contact)
    assert automation.run_automation_rules(db) == 1
    db.refresh(ticket); assert ticket.status == TicketStatus.IN_PROGRESS


def test_one_ticket_cannot_cascade_through_multiple_rules_in_one_sweep(db, contact):
    generic_rule(db, AutomationTriggerType.STATUS_AGE)
    ticket = old_waiting_ticket(db, contact)
    db.add(AutomationRule(name='Дальнейший переход', trigger_type=AutomationTriggerType.STATUS_AGE,
        from_status=TicketStatus.IN_PROGRESS, to_status=TicketStatus.WAITING_CUSTOMER, threshold_days=1, is_active=True))
    db.commit()
    assert automation.run_automation_rules(db, now=datetime.now(timezone.utc) + timedelta(days=10)) >= 1
    assert db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='automation_applied').count() == 1
    db.refresh(ticket); assert ticket.status == TicketStatus.IN_PROGRESS
