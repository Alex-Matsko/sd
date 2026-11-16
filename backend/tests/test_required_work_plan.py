"""Plan, status and timer commit together; clients see the commitment in both bots."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from tests.test_start_work import api, make_ticket
from tests.test_customer_bot_replies import bot
from app.core.enums import TicketStatus
from app.models.active_timer import ActiveTimer
from app.models.audit import AuditLog
from app.models.channel_job import ChannelJob
from app.models.time_entry import TimeEntry
from app.schemas.ticket import TicketUpdate
from app.services import tickets, time_entries


def plan():
    return {'planned_due_at': (datetime.now(timezone.utc)+timedelta(days=2)).isoformat(), 'estimated_minutes':90}


@pytest.mark.parametrize('data',[None, {}, {'estimated_minutes':90}, {'planned_due_at':None,'estimated_minutes':90},
    {'estimated_minutes':0}, {'estimated_minutes':-1}, {'planned_due_at':'2020-01-01T00:00:00Z'},
    {'planned_due_at':'2030-01-01T00:00:00'}, {'estimated_minutes':600001}])
def test_cannot_start_without_valid_plan_and_does_not_bank_previous_work(db, api, contact, engineer_user, data):
    active=make_ticket(db,contact);time_entries.start_timer(db,active,engineer_user)
    timer=time_entries.get_active_timer(db,engineer_user);timer.started_at-=timedelta(minutes=5);db.commit();started=timer.started_at
    target=make_ticket(db,contact);target.planned_due_at=target.estimated_minutes=None;db.commit()
    before=db.query(ChannelJob).filter_by(ticket_id=target.id).count()
    r=api.post(f'/tickets/{target.id}/timer/start',json=data)
    assert r.status_code in (409,422),r.text
    db.refresh(target);db.refresh(timer)
    assert target.status==TicketStatus.NEW and target.planned_due_at is None and target.estimated_minutes is None
    assert timer.ticket_id==active.id and timer.started_at==started
    assert db.query(TimeEntry).filter_by(ticket_id=active.id).count()==0
    assert db.query(ChannelJob).filter_by(ticket_id=target.id).count()==before


def test_start_saves_plan_status_and_timer_atomically_and_notifies_customer(db,api,bot,contact,engineer_user):
    t=make_ticket(db,contact);t.planned_due_at=t.estimated_minutes=None;t.channel=bot.channel;db.commit()
    r=api.post(f'/tickets/{t.id}/timer/start',json=plan());assert r.status_code==200,r.text
    db.refresh(t);assert t.status==TicketStatus.IN_PROGRESS and t.estimated_minutes==90 and t.planned_due_at
    assert time_entries.get_active_timer(db,engineer_user).ticket_id==t.id
    notices=db.query(ChannelJob).filter_by(ticket_id=t.id,channel=bot.channel).all()
    assert any('Плановый срок решения:' in x.payload.get('text','') and 'Оценка трудозатрат: 1 ч 30 мин' in x.payload.get('text','') for x in notices)
    assert db.query(TimeEntry).filter_by(ticket_id=t.id).count()==0
    assert db.query(AuditLog).filter_by(entity_type='ticket',entity_id=t.id,action='updated').count()==1


def test_api_status_change_requires_plan_and_can_save_it_in_same_request(db,api,contact):
    t=make_ticket(db,contact);t.planned_due_at=t.estimated_minutes=None;db.commit()
    r=api.patch(f'/tickets/{t.id}',json={'status':'in_progress'});assert r.status_code==400
    db.refresh(t);assert t.status==TicketStatus.NEW
    r=api.patch(f'/tickets/{t.id}',json={'status':'in_progress',**plan()});assert r.status_code==200,r.text
    db.refresh(t);assert t.status==TicketStatus.IN_PROGRESS and t.estimated_minutes==90
    assert db.query(ActiveTimer).filter_by(ticket_id=t.id).count()==0


def test_started_plan_cannot_be_erased_and_updates_notify_customer(db,api,contact,bot):
    t=make_ticket(db,contact);t.status=TicketStatus.IN_PROGRESS;t.channel=bot.channel;db.commit()
    old=t.planned_due_at
    r=api.patch(f'/tickets/{t.id}',json={'planned_due_at':None,'estimated_minutes':None});assert r.status_code==400
    db.refresh(t);assert t.planned_due_at==old and t.estimated_minutes==90
    r=api.patch(f'/tickets/{t.id}',json={**plan(),'estimated_minutes':120});assert r.status_code==200,r.text
    notices=db.query(ChannelJob).filter_by(ticket_id=t.id,channel=bot.channel).all()
    assert any('План выполнения заявки обновлён' in x.payload.get('text','') and 'Оценка трудозатрат: 2 ч' in x.payload.get('text','') for x in notices)


def test_failure_rolls_back_plan_audit_and_status(db,contact,engineer_user,monkeypatch):
    t=make_ticket(db,contact);t.planned_due_at=t.estimated_minutes=None;db.commit()
    original=tickets.transition_status
    def fail(*a,**kw):
        original(*a,**kw);raise RuntimeError('failure after status')
    monkeypatch.setattr(tickets,'transition_status',fail)
    with pytest.raises(RuntimeError): time_entries.start_timer(db,t,engineer_user,TicketUpdate(**plan()))
    db.refresh(t);assert t.status==TicketStatus.NEW and t.estimated_minutes is None and t.planned_due_at is None
    assert db.query(ActiveTimer).filter_by(ticket_id=t.id).count()==0
    assert db.query(AuditLog).filter_by(entity_type='ticket',entity_id=t.id,action='updated').count()==0


def test_automation_cannot_accept_unplanned_work(db,contact):
    from app.models.automation_rule import AutomationRule
    from app.core.enums import AutomationTriggerType
    from app.services.automation import _preflight
    t=make_ticket(db,contact);t.planned_due_at=t.estimated_minutes=None;db.commit()
    rule=AutomationRule(name='Start',trigger_type=AutomationTriggerType.STATUS_AGE,from_status=TicketStatus.NEW,
        to_status=TicketStatus.IN_PROGRESS,threshold_days=1,is_active=True)
    db.add(rule); db.flush()
    assert 'укажите' in _preflight(db,rule,t)
