# coding: utf-8
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import Channel, MessageDirection, NotificationType, TicketStatus, UserRole
from app.db import get_db
from app.main import app
from app.models.automation_rule import AutomationRule, AutomationRun
from app.models.audit import AuditLog
from app.models.channel_job import ChannelJob
from app.models.message import Message
from app.models.notification import Notification
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import automation, channel_queue, max_channel, messages, tickets


@pytest.fixture()
def api(db):
    actor = db.query(User).filter_by(role=UserRole.ADMIN).first()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        yield client
    app.dependency_overrides = previous


def payload(**changes):
    result = dict(name='Напоминание', trigger_type='status_age', from_status='in_progress', delay_hours=1,
                actions=[dict(type='internal_note', text='Проверить {{ticket_number}}')])
    result.update(changes)
    return result


def ticket_and_rule(api, db, contact, **changes):
    db.query(AutomationRule).update({'is_active': False}); db.commit()
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type='incident', channel='portal',
        subject='Проверка напоминаний', manual_priority='P3', manual_priority_reason='test'), actor=None)
    tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, None)
    response = api.post('/automation-rules', json=payload(is_active=True, filters={'organization_id': contact.organization_id}, **changes))
    assert response.status_code == 201, response.text
    return ticket, db.get(AutomationRule, response.json()['id']), datetime.now(timezone.utc) + timedelta(hours=2)


def test_preview_is_read_only_filtered_and_uses_customer_safe_url(api, db, contact, monkeypatch):
    monkeypatch.setattr('app.config.settings.portal_base_url', 'https://service.o-horizons.com/portal')
    ticket, rule, future = ticket_and_rule(api, db, contact, actions=[{'type': 'client_reminder', 'text': '{{client_name}} {{ticket_url}}'}])
    result = automation.preview_rule(db, rule, future)
    assert result['matched_count'] == result['ready_count'] == 1
    assert f'/portal?ticket={ticket.id}' in result['samples'][0]['actions'][0]['text']
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0
    assert db.query(AutomationRun).filter_by(rule_id=rule.id).count() == 0
    assert db.query(ChannelJob).filter_by(ticket_id=ticket.id).count() == 0
    # The real endpoint validates the unsaved draft, with no actions or activation.
    response = api.post('/automation-rules/preview', json=payload(filters={'priorities': ['P1']}))
    assert response.status_code == 200 and all(s['ticket_id'] != ticket.id for s in response.json()['samples'])


def test_notes_execute_once_and_are_marked_as_automatic(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact)
    assert automation.run_automation_rules(db, future) == 1
    assert automation.run_automation_rules(db, future + timedelta(days=10)) == 0
    note = db.query(Message).filter_by(ticket_id=ticket.id).one()
    assert note.direction == MessageDirection.INTERNAL_NOTE and note.is_automated
    assert ticket.display_number in note.body
    assert db.query(ChannelJob).filter_by(ticket_id=ticket.id).count() == 0
    assert db.query(AutomationRun).filter_by(rule_id=rule.id).one().state == 'applied'


def test_repeat_interval_limit_and_no_catchup_burst(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact, repeat_hours=24, max_runs=3)
    assert automation.run_automation_rules(db, future) == 1
    assert automation.run_automation_rules(db, future + timedelta(hours=23)) == 0
    late = future + timedelta(days=10)
    assert automation.run_automation_rules(db, late) == 1
    assert automation.run_automation_rules(db, late) == 0
    assert automation.run_automation_rules(db, late + timedelta(hours=24)) == 1
    assert automation.run_automation_rules(db, late + timedelta(days=10)) == 0
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 3


def test_customer_reply_and_status_changes_reset_episode(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact)
    rule.trigger_type = 'status_without_reply'; rule.delay_hours = 24; db.commit()
    future += timedelta(days=2)
    assert automation.run_automation_rules(db, future) == 1
    message = messages.add_message(db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body='Новое уточнение'), author_contact=contact)
    message.created_at = future + timedelta(hours=1); db.commit()
    assert automation.run_automation_rules(db, future + timedelta(hours=2)) == 0
    assert automation.run_automation_rules(db, future + timedelta(days=2)) == 1
    tickets.transition_status(db, ticket, TicketStatus.WAITING_CUSTOMER, None)
    assert automation.run_automation_rules(db, future + timedelta(days=100)) == 0


def test_portal_reminder_does_not_count_as_engineer_response(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact, actions=[{'type': 'client_reminder', 'text': 'Ждём вашего ответа'}])
    assert automation.run_automation_rules(db, future) == 1
    db.refresh(ticket)
    assert ticket.first_response_at is None
    message = db.query(Message).filter_by(ticket_id=ticket.id).one()
    assert message.direction == MessageDirection.OUTBOUND and message.is_automated
    result = api.get(f'/tickets/{ticket.id}/messages')
    assert result.status_code == 200 and result.json()[0]['is_automated'] is True


def test_external_reminder_queues_without_sending_or_sla_and_blocks_repeat(api, db, contact, monkeypatch):
    monkeypatch.setattr(max_channel, 'load_max_config', lambda db: SimpleNamespace(token='fake', base_url='http://invalid'))
    monkeypatch.setattr(max_channel, '_find_chat_state', lambda db, contact_id: SimpleNamespace(chat_id='fake-customer'))
    sent = []
    monkeypatch.setattr(max_channel.max_client, 'send_message', lambda *args, **kwargs: sent.append(True) or {'message': {'body': {'mid': 'fake-mid'}}})
    ticket, rule, future = ticket_and_rule(api, db, contact, actions=[{'type': 'client_reminder', 'channel': 'max', 'text': 'Напоминание'}], repeat_hours=1, max_runs=3)
    assert automation.run_automation_rules(db, future) == 1 and sent == []
    job = db.query(ChannelJob).filter_by(ticket_id=ticket.id).one()
    assert automation.run_automation_rules(db, future + timedelta(hours=2)) == 0
    assert channel_queue.process_outbound(db, *channel_queue.claim(db, 'outbound', job.id)) is True
    db.refresh(ticket); assert ticket.first_response_at is None
    assert sent == [True]
    assert automation.run_automation_rules(db, future + timedelta(hours=2)) == 1


def test_all_actions_rollback_together_and_failures_are_bounded(api, db, contact, monkeypatch):
    ticket, rule, future = ticket_and_rule(api, db, contact, actions=[{'type': 'internal_note', 'text': 'Первое действие'}, {'type': 'client_reminder', 'text': 'Второе действие'}])
    original = messages.add_message
    def fail_second(db, ticket, payload, *args, **kwargs):
        if payload.direction == MessageDirection.OUTBOUND:
            raise RuntimeError('DO NOT EXPOSE provider secrets')
        return original(db, ticket, payload, *args, **kwargs)
    monkeypatch.setattr(messages, 'add_message', fail_second)
    assert automation.run_automation_rules(db, future) == 0
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0
    run = db.query(AutomationRun).filter_by(rule_id=rule.id).one()
    assert run.state == 'error' and run.attempts == 1 and 'DO NOT EXPOSE' not in run.error
    assert automation.run_automation_rules(db, future + timedelta(minutes=30)) == 0
    db.refresh(run); assert run.attempts == 1
    for offset in (1, 2, 3, 4):
        assert automation.run_automation_rules(db, future + timedelta(hours=offset)) == 0
    db.refresh(run); assert run.attempts == 3
    response = api.get(f'/automation-rules/{rule.id}/runs')
    assert response.status_code == 200 and response.json()[0]['error'] == run.error
    assert api.post(f'/automation-rules/{rule.id}/runs/{run.id}/retry').status_code == 204
    monkeypatch.setattr(messages, 'add_message', original)
    assert automation.run_automation_rules(db, future + timedelta(hours=5)) == 1
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 2


def test_missing_client_channel_fails_before_internal_side_effects(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact, actions=[{'type': 'internal_note', 'text': 'Не создавать'}, {'type': 'client_reminder', 'channel': 'max', 'text': 'Не отправлять'}])
    result = automation.preview_rule(db, rule, future)
    assert result['ready_count'] == 0 and result['samples'][0]['error']
    assert automation.run_automation_rules(db, future) == 0
    assert db.query(Message).filter_by(ticket_id=ticket.id).count() == 0


def test_internal_staff_recipient_does_not_broadcast_to_every_subscriber(api, db, contact, engineer_user, monkeypatch):
    monkeypatch.setattr(max_channel, 'load_max_config', lambda db: SimpleNamespace())
    admin = db.query(User).filter_by(role=UserRole.ADMIN).first()
    for user in (admin, engineer_user):
        user.max_id, user.max_chat_id = f'u-{user.id}', f'c-{user.id}'
        user.max_notification_scope, user.max_notify_new_tickets = ('assigned' if user == engineer_user else 'all'), True
    db.commit()
    ticket, rule, future = ticket_and_rule(api, db, contact, actions=[{'type': 'notify_staff', 'recipient': 'assignee', 'text': 'Напомнить исполнителю'}])
    ticket.assigned_engineer_id = engineer_user.id; db.commit()
    before = db.query(ChannelJob).filter_by(ticket_id=ticket.id).count()
    assert automation.run_automation_rules(db, future) == 1
    notices = db.query(Notification).filter_by(ticket_id=ticket.id, type=NotificationType.AUTOMATION_REMINDER).all()
    assert [n.user_id for n in notices] == [engineer_user.id]
    jobs = db.query(ChannelJob).filter_by(ticket_id=ticket.id).order_by(ChannelJob.id).all()
    assert len(jobs) == before + 1 and jobs[-1].payload['staff_user_id'] == engineer_user.id


def test_deadline_uses_plan_or_unpaused_sla(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact, trigger_type='deadline_overdue')
    assert automation.run_automation_rules(db, future) == 0
    ticket.planned_due_at = future - timedelta(minutes=30); db.commit()
    assert automation.run_automation_rules(db, future) == 0
    assert automation.run_automation_rules(db, future + timedelta(hours=1)) == 1
    ticket.planned_due_at = None
    ticket.sla_resolution_due_at = future - timedelta(days=2)
    ticket.sla_paused_at = future - timedelta(days=3); db.commit()
    assert automation.run_automation_rules(db, future) == 0


@pytest.mark.parametrize('changes', [
    {'actions': [{'type': 'client_reminder', 'text': '{{internal_password}}'}]},
    {'actions': [{'type': 'notify_staff', 'text': 'Test', 'recipient': 'users'}]},
    {'actions': []}, {'repeat_hours': 0}, {'delay_hours': 0},
    {'filters': {'unassigned': True, 'assigned_engineer_id': 123}},
    {'filters': {'unknown_field': 'x'}},
    {'to_status': 'resolved', 'actions': [{'type': 'change_status'}, {'type': 'internal_note', 'text': 'X'}]},
    {'to_status': 'resolved', 'repeat_hours': 24, 'actions': [{'type': 'change_status'}]},
])
def test_invalid_builder_rejected(api, changes):
    values = payload(); values.update(changes)
    assert api.post('/automation-rules', json=values).status_code == 422


def test_reminders_coexist_and_edits_bump_execution_version(api, db, contact, engineer_user):
    ticket, rule, future = ticket_and_rule(api, db, contact)
    values = payload(is_active=True); values.update(name='Другое напоминание')
    assert api.post('/automation-rules', json=values).status_code == 201
    assert automation.run_automation_rules(db, future) >= 2
    original_revision = rule.revision
    assert api.patch(f'/automation-rules/{rule.id}', json={'name': 'Переименовано'}).status_code == 200
    db.refresh(rule); assert rule.revision == original_revision
    assert api.patch(f'/automation-rules/{rule.id}', json={'delay_hours': 2}).status_code == 200
    db.refresh(rule); assert rule.revision == original_revision + 1
    app.dependency_overrides[get_current_user] = lambda: engineer_user
    assert api.post('/automation-rules/preview', json=payload()).status_code == 403
    assert api.get(f'/automation-rules/{rule.id}/runs').status_code == 403


def test_filtered_status_rules_can_coexist_without_ambiguous_transitions(api):
    first = payload(is_active=True, actions=[{'type': 'change_status'}], to_status='resolved', filters={'priorities': ['P1']})
    second = {**first, 'filters': {'priorities': ['P2']}}
    assert api.post('/automation-rules', json=first).status_code == 201
    assert api.post('/automation-rules', json=second).status_code == 201
    assert api.post('/automation-rules', json={**first, 'filters': {}}).status_code == 409


def test_schedule_can_be_created_disabled(api, contact):
    response = api.post('/ticket-schedules', json={'name': 'Профилактика', 'contact_id': contact.id,
        'subject': 'Проверка резервных копий', 'cadence': 'weekly', 'day_of_week': 1, 'is_active': False})
    assert response.status_code == 201 and response.json()['is_active'] is False


def test_same_timestamp_reentry_is_a_new_status_episode(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact)
    anchor = automation._time_in_current_status(db, ticket)
    assert automation.run_automation_rules(db, future) == 1
    tickets.transition_status(db, ticket, TicketStatus.WAITING_CUSTOMER, None)
    tickets.transition_status(db, ticket, TicketStatus.IN_PROGRESS, None)
    latest = db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='status_changed').order_by(AuditLog.id.desc()).first()
    latest.created_at = anchor; db.commit()
    assert automation.run_automation_rules(db, future) == 1
    assert db.query(AutomationRun).filter_by(rule_id=rule.id).count() == 2


def test_channel_and_priority_filters_limit_candidates(api, db, contact):
    ticket, rule, future = ticket_and_rule(api, db, contact)
    rule.filters = {'organization_id': contact.organization_id, 'channels': ['max'], 'priorities': ['P3']}; db.commit()
    assert automation.run_automation_rules(db, future) == 0
    rule.filters = {'organization_id': contact.organization_id, 'channels': ['portal'], 'priorities': ['P1', 'P3']}; db.commit()
    assert automation.run_automation_rules(db, future) == 1
