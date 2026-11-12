from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.core.enums import Channel, MessageDirection, Priority, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.channel_job import ChannelJob
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.models.routing import RoutingRule
from app.models.user import User
from app.schemas.ticket import TicketCreate
from app.services import channel_queue, login_guard, max_channel, staff_notifications, tickets


@pytest.fixture(autouse=True)
def fake_max(monkeypatch):
    config = max_channel.MaxConfig(token='test', base_url='http://local-max.invalid', poll_timeout_seconds=1)
    monkeypatch.setattr(max_channel, 'load_max_config', lambda db: config)
    sent = []
    monkeypatch.setattr(max_channel.max_client, 'send_message', lambda *args, **kwargs:
                        sent.append((args, kwargs)) or {'message': {'body': {'mid': f'mid.{len(sent)}'}}})
    login_guard.guard.reset()
    yield sent
    login_guard.guard.reset()


@pytest.fixture()
def actor(db):
    return db.query(User).filter(User.role == UserRole.ADMIN).first()


@pytest.fixture()
def api(db, actor):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: actor
    with TestClient(app) as client:
        yield client
    app.dependency_overrides = previous


def update(text, user_id='max-staff-test', chat_id='staff-chat-test', kind='message_created'):
    return {'update_type': kind, 'message': {'sender': {'user_id': user_id, 'name': 'Сотрудник'},
        'recipient': {'chat_id': chat_id, 'chat_type': 'dialog'},
        'body': {'mid': f'mid.{uuid4()}', 'text': text}}}


def subscribed(db, user, suffix=''):
    user.max_id, user.max_chat_id = f'max-{user.id}{suffix}', f'chat-{user.id}{suffix}'
    user.max_notify_new_tickets = True
    db.commit()


def make_ticket(db, contact, actor=None, engineer=None, channel=Channel.PORTAL):
    rule = None
    if engineer:
        rule = RoutingRule(rule_type='organization_to_engineer', order=0, is_active=True,
                           organization_id=contact.organization_id, target_engineer_id=engineer.id)
        db.add(rule); db.commit()
    try:
        return tickets.create_ticket(db, TicketCreate(contact_id=contact.id, type=TicketType.INCIDENT, channel=channel,
            subject='Новая заявка для MAX', manual_priority=Priority.P3, manual_priority_reason='test'), actor=actor)
    finally:
        if rule is not None:
            db.delete(rule); db.commit()


def jobs(db, ticket):
    return db.query(ChannelJob).filter(ChannelJob.ticket_id == ticket.id,
        ChannelJob.event_key.like('staff:max:new-ticket:%')).all()


def test_code_rotates_hashes_and_links_only_once(api, db, actor, fake_max):
    before_tickets, before_contacts = db.query(Ticket).count(), db.query(Contact).count()
    old = api.post('/auth/me/max-link-code').json()['code']
    response = api.post('/auth/me/max-link-code')
    assert response.status_code == 200
    code = response.json()['code']
    assert len(code) == 12 and code != old
    assert actor.max_link_code_hash == hashlib.sha256(code.encode()).hexdigest()
    assert actor.max_link_code_hash != code
    max_channel.handle_update(db, update(f'/link {old}'))
    assert actor.max_id is None
    max_channel.handle_update(db, update(f'/link {code.lower()}'))
    db.refresh(actor)
    assert actor.max_id == 'max-staff-test' and actor.max_chat_id == 'staff-chat-test'
    assert actor.max_link_code_hash is None and actor.max_link_code_expires_at is None
    assert actor.max_notify_new_tickets is True
    visible = api.get('/auth/me').json()
    assert visible['max_linked'] is True and visible['max_notify_new_tickets'] is True
    assert 'max_id' not in visible and 'max_chat_id' not in visible and 'max_link_code_hash' not in visible
    max_channel.handle_update(db, update(f'/link {code}', user_id='another', chat_id='another-chat'))
    db.refresh(actor); assert actor.max_id == 'max-staff-test'
    max_channel.handle_update(db, update('Новая заявка'))
    assert db.query(Ticket).count() == before_tickets
    assert db.query(Contact).count() == before_contacts
    assert api.post('/auth/me/max-link-code').status_code == 409
    assert api.patch('/auth/me/max-notifications', json={'enabled': False}).json()['max_notify_new_tickets'] is False
    assert api.post('/auth/me/max-unlink').json()['max_linked'] is False
    db.refresh(actor)
    assert actor.max_id is None and actor.max_chat_id is None and actor.max_notify_new_tickets is False


@pytest.mark.parametrize('inactive', [False, True])
def test_expired_or_inactive_staff_code_cannot_link(api, db, actor, inactive):
    code = api.post('/auth/me/max-link-code').json()['code']
    if inactive: actor.is_active = False
    else: actor.max_link_code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    max_channel.handle_update(db, update(f'/link {code}'))
    db.refresh(actor); assert actor.max_id is None


def test_invalid_link_never_creates_a_ticket_and_is_throttled(db, fake_max):
    before = db.query(Ticket).count()
    for _ in range(11): max_channel.handle_update(db, update('/link invalid'))
    assert db.query(Ticket).count() == before
    assert 'Слишком много попыток' in fake_max[-1][0][3]


def test_max_account_cannot_take_over_another_staff_binding(api, db, actor, engineer_user):
    subscribed(db, engineer_user)
    code = api.post('/auth/me/max-link-code').json()['code']
    max_channel.handle_update(db, update(f'/link {code}', engineer_user.max_id, engineer_user.max_chat_id))
    db.refresh(actor); assert actor.max_id is None
    db.refresh(engineer_user); assert engineer_user.max_linked


def test_disabled_channel_cannot_issue_code(api, monkeypatch):
    monkeypatch.setattr(max_channel, 'load_max_config', lambda db: None)
    assert api.post('/auth/me/max-link-code').status_code == 409


@pytest.mark.parametrize('channel', list(Channel))
def test_admin_receives_new_ticket_from_every_channel_once(db, actor, contact, fake_max, monkeypatch, channel):
    monkeypatch.setattr('app.config.settings.staff_base_url', 'https://desk.example.org')
    subscribed(db, actor)
    ticket = make_ticket(db, contact, channel=channel)
    notice = jobs(db, ticket)
    assert len(notice) == 1
    job = notice[0]
    assert job.payload['recipient'] == actor.max_chat_id
    assert ticket.display_number in job.payload['text'] and contact.organization.name in job.payload['text']
    assert f'https://desk.example.org/tickets/{ticket.id}' in job.payload['text']
    assert 'Приоритет: P3' in job.payload['text']
    staff_notifications.notify_new_ticket(db, ticket); db.commit()
    assert len(jobs(db, ticket)) == 1
    assert fake_max == []
    assert channel_queue.process_outbound(db, *channel_queue.claim(db, 'outbound', job.id)) is True
    db.refresh(job); assert job.state == 'sent'
    assert len(fake_max) == 1


def test_all_new_subscription_includes_auto_assigned_tickets(db, actor, contact, engineer_user):
    subscribed(db, actor)
    ticket = make_ticket(db, contact, engineer=engineer_user)
    assert len(jobs(db, ticket)) == 1


def test_engineer_does_not_receive_inaccessible_tickets(db, actor, contact, engineer_user):
    subscribed(db, engineer_user)
    private = make_ticket(db, contact, engineer=actor)
    assert jobs(db, private) == []
    unassigned = make_ticket(db, contact)
    assert jobs(db, unassigned) == []
    assigned = make_ticket(db, contact, engineer=engineer_user)
    assert len(jobs(db, assigned)) == 1


def test_own_tickets_and_unsubscribed_accounts_do_not_notify(db, actor, contact):
    subscribed(db, actor)
    own = make_ticket(db, contact, actor=actor)
    assert jobs(db, own) == []
    actor.max_notify_new_tickets = False; db.commit()
    assert jobs(db, make_ticket(db, contact)) == []


@pytest.mark.parametrize('change', ['unlink', 'disable', 'deactivate', 'rebind', 'lost_access'])
def test_delivery_rechecks_binding_subscription_and_access(db, actor, engineer_user, contact, fake_max, change):
    subscribed(db, actor)
    ticket = make_ticket(db, contact, engineer=engineer_user)
    job = jobs(db, ticket)[0]
    if change == 'unlink': actor.max_id = actor.max_chat_id = None
    if change == 'disable': actor.max_notify_new_tickets = False
    if change == 'deactivate': actor.is_active = False
    if change == 'rebind': actor.max_id = 'another-max'
    if change == 'lost_access': actor.role = UserRole.ENGINEER
    db.commit()
    assert channel_queue.process_outbound(db, *channel_queue.claim(db, 'outbound', job.id)) is True
    db.refresh(job); assert job.state == 'discarded'
    assert fake_max == []


def test_link_event_and_confirmation_commit_together_without_customer_ticket(api, db, actor, fake_max):
    code = api.post('/auth/me/max-link-code').json()['code']
    initial = db.query(Ticket).count()
    config = max_channel.load_max_config(db)
    raw = update(f'/link {code}')
    id = channel_queue.capture_update(db, Channel.MAX, raw, config)
    assert channel_queue.process_inbound(db, *channel_queue.claim(db, 'inbound', id)) is True
    db.refresh(actor)
    assert actor.max_linked and actor.max_notify_new_tickets
    replies = db.query(ChannelJob).filter(ChannelJob.event_key.like(f'event:{id}:reply:%')).all()
    assert len(replies) == 1
    assert replies[0].payload['recipient'] == 'staff-chat-test'
    assert db.query(Ticket).count() == initial
    assert fake_max == []
    assert channel_queue.capture_update(db, Channel.MAX, raw, config) is None


def test_group_cannot_consume_a_private_staff_code(api, db, actor):
    code = api.post('/auth/me/max-link-code').json()['code']
    raw = update(f'/link {code}')
    raw['message']['recipient']['chat_type'] = 'chat'
    max_channel.handle_update(db, raw)
    db.refresh(actor)
    assert not actor.max_linked and actor.max_link_code_hash is not None


@pytest.fixture()
def fake_telegram(monkeypatch):
    from app.services import telegram_channel, telegram_client
    config = SimpleNamespace(base_url='http://local-telegram.invalid', token='test', poll_timeout_seconds=1)
    monkeypatch.setattr(telegram_channel, 'load_telegram_config', lambda db: config)
    sent = []
    monkeypatch.setattr(telegram_client, 'send_message', lambda *args, **kwargs: sent.append(args) or {'message_id': len(sent)})
    return sent


def telegram_subscribe(db, user, scope):
    user.telegram_id = f'tg-{user.id}'
    user.telegram_notification_scope = scope
    db.commit()


def telegram_jobs(db, ticket):
    return db.query(ChannelJob).filter(ChannelJob.ticket_id == ticket.id, ChannelJob.channel == 'telegram',
                                      ChannelJob.event_key.like('staff:telegram:new-ticket:%')).all()


def test_telegram_owner_sees_unassigned_and_engineer_sees_only_personal_tickets(db, actor, contact, engineer_user, fake_telegram):
    telegram_subscribe(db, actor, 'all')
    telegram_subscribe(db, engineer_user, 'assigned')
    unassigned = make_ticket(db, contact)
    assert {j.payload['staff_user_id'] for j in telegram_jobs(db, unassigned)} == {actor.id}
    personal = make_ticket(db, contact, engineer=engineer_user)
    assert {j.payload['staff_user_id'] for j in telegram_jobs(db, personal)} == {actor.id, engineer_user.id}
    other = make_ticket(db, contact, engineer=actor)
    assert {j.payload['staff_user_id'] for j in telegram_jobs(db, other)} == {actor.id}
    staff_notifications.notify_new_ticket(db, personal); db.commit()
    assert len(telegram_jobs(db, personal)) == 2
    assert fake_telegram == []


def test_telegram_customer_replies_and_sla_follow_the_same_scope(db, actor, contact, engineer_user, fake_telegram):
    from app.core.enums import NotificationType
    telegram_subscribe(db, actor, 'all')
    telegram_subscribe(db, engineer_user, 'assigned')
    ticket = make_ticket(db, contact, engineer=engineer_user)
    staff_notifications.notify_customer_reply(db, ticket)
    staff_notifications.notify(db, {engineer_user.id}, NotificationType.SLA_RESOLUTION_WARNING, ticket, 'Риск SLA')
    db.commit()
    events = db.query(ChannelJob).filter_by(channel='telegram', ticket_id=ticket.id).all()
    events = [j for j in events if j.payload.get('staff_notice') == 'ticket_event']
    assert sorted(j.payload['staff_user_id'] for j in events) == sorted([actor.id, actor.id, engineer_user.id, engineer_user.id])
    assert fake_telegram == []


def test_telegram_engineer_cannot_select_all_and_can_switch_off(api, db, actor, engineer_user, fake_telegram):
    telegram_subscribe(db, engineer_user, 'assigned')
    app.dependency_overrides[get_current_user] = lambda: engineer_user
    assert api.patch('/auth/me/telegram-notifications', json={'scope': 'all'}).status_code == 403
    assert api.patch('/auth/me/telegram-notifications', json={'scope': 'off'}).json()['telegram_notification_scope'] == 'off'
    assert api.patch('/auth/me/telegram-notifications', json={'scope': 'assigned'}).status_code == 200
    assert api.patch('/auth/me/telegram-notifications', json={'scope': 'unknown'}).status_code == 422
    assert api.post('/auth/me/telegram-unlink').json()['telegram_id'] is None
    db.refresh(engineer_user); assert engineer_user.telegram_notification_scope == 'off'


@pytest.mark.parametrize('scope_change', ['off', 'unlink', 'reassigned'])
def test_telegram_delayed_delivery_rechecks_scope_and_assignment(db, contact, engineer_user, actor, fake_telegram, scope_change):
    telegram_subscribe(db, engineer_user, 'assigned')
    ticket = make_ticket(db, contact, engineer=engineer_user)
    job = telegram_jobs(db, ticket)[0]
    if scope_change == 'off': engineer_user.telegram_notification_scope = 'off'
    if scope_change == 'unlink': engineer_user.telegram_id = None
    if scope_change == 'reassigned': ticket.assigned_engineer_id = actor.id
    db.commit()
    assert channel_queue.process_outbound(db, *channel_queue.claim(db, 'outbound', job.id)) is True
    db.refresh(job); assert job.state == 'discarded'
    assert fake_telegram == []


@pytest.mark.parametrize('is_engineer', [False, True])
def test_telegram_link_sets_expected_default_and_staff_text_never_creates_tickets(db, actor, engineer_user, fake_telegram, is_engineer):
    from app.services import telegram_channel
    user = engineer_user if is_engineer else actor
    user.telegram_link_code = 'ABCDEF01'
    user.telegram_link_code_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    db.commit()
    initial = db.query(Ticket).count()
    raw = {'update_id': 123, 'message': {'message_id': 1, 'from': {'id': 12345678},
        'chat': {'id': 12345678, 'type': 'private'}, 'text': '/link ABCDEF01'}}
    telegram_channel.handle_update(db, raw)
    db.refresh(user)
    assert user.telegram_id == '12345678'
    assert user.telegram_notification_scope == ('assigned' if is_engineer else 'all')
    raw['message']['text'] = 'Новая заявка'
    telegram_channel.handle_update(db, raw)
    assert db.query(Ticket).count() == initial
