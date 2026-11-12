from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import Channel, TicketStatus, TicketType
from app.db import get_db
from app.main import app
from app.models.active_timer import ActiveTimer
from app.models.audit import AuditLog
from app.models.channel_job import ChannelJob
from app.models.time_entry import TimeEntry
from app.schemas.ticket import TicketCreate
from app.services import time_entries, tickets


@pytest.fixture()
def api(db, engineer_user):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: engineer_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous


def make_ticket(db, contact, status=TicketStatus.NEW, engineer=None):
    ticket = tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT,
        channel=Channel.PORTAL, subject='Start work test', manual_priority='P3', manual_priority_reason='test'), actor=None)
    ticket.status = status
    if status == TicketStatus.ASSIGNED:
        ticket.assigned_engineer_id = engineer.id
    if status == TicketStatus.RESOLVED:
        ticket.resolved_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    return ticket


def changes(db, ticket):
    return db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='status_changed').all()


@pytest.mark.parametrize('status', [TicketStatus.NEW, TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS,
                                   TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_THIRD_PARTY, TicketStatus.RESOLVED])
def test_start_work_changes_status_with_audit_and_preserves_sla_response(api, db, contact, engineer_user, status):
    ticket = make_ticket(db, contact, status, engineer_user)
    resolved_at = ticket.resolved_at
    response = api.post(f'/tickets/{ticket.id}/timer/start')
    assert response.status_code == 200, response.text
    assert response.json()['running'] is True and response.json()['ticket_id'] == ticket.id
    db.refresh(ticket)
    assert ticket.status == TicketStatus.IN_PROGRESS
    assert ticket.first_response_at is None and ticket.resolved_at == resolved_at
    assert ticket.reopen_count == (1 if status == TicketStatus.RESOLVED else 0)
    history = changes(db, ticket)
    assert len(history) == (0 if status == TicketStatus.IN_PROGRESS else 1)
    if history:
        assert history[0].user_id == engineer_user.id
        assert history[0].changes == {'from': status.value, 'to': 'in_progress'}
    assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).count() == 0


def test_repeated_start_keeps_elapsed_time_and_does_not_notify_twice(api, db, contact, engineer_user):
    ticket = make_ticket(db, contact)
    first = api.post(f'/tickets/{ticket.id}/timer/start').json()
    timer = time_entries.get_active_timer(db, engineer_user)
    timer.started_at -= timedelta(minutes=2); db.commit()
    started = timer.started_at
    jobs_before = db.query(ChannelJob).filter_by(ticket_id=ticket.id).count()
    response = api.post(f'/tickets/{ticket.id}/timer/start')
    assert response.status_code == 200
    assert response.json()['ticket_id'] == first['ticket_id']
    db.refresh(timer)
    assert timer.started_at == started
    assert db.query(ActiveTimer).filter_by(user_id=engineer_user.id).count() == 1
    assert len(changes(db, ticket)) == 1
    assert db.query(ChannelJob).filter_by(ticket_id=ticket.id).count() == jobs_before


@pytest.mark.parametrize('status', [TicketStatus.CLOSED, TicketStatus.CANCELLED])
def test_terminal_ticket_cannot_stop_or_replace_the_current_timer(api, db, contact, engineer_user, status):
    first = make_ticket(db, contact)
    active = time_entries.start_timer(db, first, engineer_user)
    active.started_at -= timedelta(minutes=2); db.commit()
    started_at = active.started_at
    terminal = make_ticket(db, contact, status)
    response = api.post(f'/tickets/{terminal.id}/timer/start')
    assert response.status_code == 409
    db.refresh(active); db.refresh(terminal)
    assert active.ticket_id == first.id and active.started_at == started_at
    assert terminal.status == status and changes(db, terminal) == []
    assert db.query(TimeEntry).filter_by(ticket_id=first.id).count() == 0


def test_switch_banks_previous_work_and_start_new_work_in_one_request(api, db, contact, engineer_user):
    first = make_ticket(db, contact)
    second = make_ticket(db, contact)
    timer = time_entries.start_timer(db, first, engineer_user)
    timer.started_at = datetime.now(timezone.utc) - timedelta(seconds=115); db.commit()
    response = api.post(f'/tickets/{second.id}/timer/start')
    assert response.status_code == 200
    db.refresh(first); db.refresh(second)
    assert first.status == second.status == TicketStatus.IN_PROGRESS
    entry = db.query(TimeEntry).filter_by(ticket_id=first.id).one()
    assert entry.duration_minutes == 2 and entry.engineer_id == engineer_user.id
    assert time_entries.get_active_timer(db, engineer_user).ticket_id == second.id
    assert db.query(TimeEntry).filter_by(ticket_id=second.id).count() == 0


def test_failure_rolls_back_status_notifications_banking_and_timer_switch(db, contact, engineer_user, monkeypatch):
    first = make_ticket(db, contact)
    second = make_ticket(db, contact)
    timer = time_entries.start_timer(db, first, engineer_user)
    timer.started_at -= timedelta(minutes=2); db.commit()
    started = timer.started_at
    original = tickets.transition_status
    def fail_after_status(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('failed after status flush')
    monkeypatch.setattr(tickets, 'transition_status', fail_after_status)
    with pytest.raises(RuntimeError):
        time_entries.start_timer(db, second, engineer_user)
    db.expire_all()
    assert second.status == TicketStatus.NEW and changes(db, second) == []
    assert time_entries.get_active_timer(db, engineer_user).ticket_id == first.id
    assert time_entries.get_active_timer(db, engineer_user).started_at == started
    assert db.query(TimeEntry).filter_by(ticket_id=first.id).count() == 0
    assert db.query(ChannelJob).filter_by(ticket_id=second.id).count() == 0


def test_resuming_while_the_same_timer_is_running_keeps_elapsed_and_resumes_sla(api, db, contact, engineer_user):
    ticket = make_ticket(db, contact)
    timer = time_entries.start_timer(db, ticket, engineer_user)
    timer.started_at -= timedelta(minutes=2); db.commit()
    started = timer.started_at
    tickets.transition_status(db, ticket, TicketStatus.WAITING_CUSTOMER, engineer_user)
    ticket.sla_paused_at = datetime.now(timezone.utc) - timedelta(minutes=10); db.commit()
    assert api.post(f'/tickets/{ticket.id}/timer/start').status_code == 200
    db.refresh(ticket); db.refresh(timer)
    assert ticket.status == TicketStatus.IN_PROGRESS and ticket.sla_paused_at is None
    assert ticket.sla_paused_minutes_total >= 10 and timer.started_at == started


def test_stop_does_not_mark_work_as_completed(api, db, contact, engineer_user):
    ticket = make_ticket(db, contact)
    assert api.post(f'/tickets/{ticket.id}/timer/start').status_code == 200
    assert api.post('/tickets/timer/stop').status_code == 200
    db.refresh(ticket)
    assert ticket.status == TicketStatus.IN_PROGRESS


def test_another_engineers_ticket_is_not_accessible(api, db, contact, engineer_user):
    from app.models.user import User
    from app.core.enums import UserRole
    other = db.query(User).filter_by(role=UserRole.ADMIN).first()
    ticket = make_ticket(db, contact, TicketStatus.ASSIGNED, other)
    assert api.post(f'/tickets/{ticket.id}/timer/start').status_code == 404
    with pytest.raises(time_entries.TimerTicketNotFound):
        time_entries.start_timer(db, ticket, engineer_user)
    db.refresh(ticket)
    assert ticket.status == TicketStatus.ASSIGNED
    assert time_entries.get_active_timer(db, engineer_user) is None
