"""Customer isolation, credential revocation and work accounting regressions.

All providers are disabled or replaced by the existing fake bot transports.
"""
import asyncio
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from tests.test_customer_bot_replies import bot, make, state
from app.core.enums import Channel, TicketStatus, UserRole, NotificationType
from app.core.security import create_access_token, create_portal_access_token
from app.db import get_db, engine, SessionLocal
from app.main import app
from app.models.active_timer import ActiveTimer
from app.models.audit import AuditLog
from app.models.contact import Contact, ContactEmail, ContactPhone
from app.models.notification import Notification
from app.models.organization import Organization
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketUpdate
from app.services import customer_acceptance, email_channel, login_guard, max_channel, messenger_common, portal, telegram_channel, tickets, time_entries


@pytest.fixture(autouse=True)
def no_external_delivery(monkeypatch):
    for name, module in [('max', max_channel), ('telegram', telegram_channel), ('email', email_channel)]:
        monkeypatch.setattr(module, f'load_{name}_config', lambda db: None)
    login_guard.guard.reset()
    yield
    login_guard.guard.reset()


@pytest.fixture()
def client(db):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides = previous


def headers(user):
    return {'Authorization': 'Bearer ' + create_access_token(user.id, user.role.value, user.auth_version)}


def portal_headers(contact):
    return {'Authorization': 'Bearer ' + create_portal_access_token(contact.id, contact.portal_auth_version)}


@pytest.mark.parametrize('legacy_prompt', [False, True])
def test_typed_phone_never_grants_another_contacts_history(db, contact, bot, legacy_prompt):
    other = Organization(name='Other customer'); db.add(other); db.flush()
    victim = Contact(organization_id=other.id, full_name='Private customer', can_view_org_tickets=True)
    db.add(victim); db.flush()
    db.add(ContactPhone(contact_id=victim.id, phone='+7 916 123-45-67', is_primary=True)); db.commit()
    private = make(db, victim, channel=Channel(bot.channel))
    conversation = state(db, bot)
    if legacy_prompt:
        conversation.awaiting_phone_confirmation = True; db.commit()
    else:
        bot.incoming(bot.event('связать телефон'))
    bot.incoming(bot.event('89161234567'))
    db.refresh(conversation); db.refresh(contact); db.refresh(victim); db.refresh(private)
    assert conversation.contact_id == contact.id and contact.organization_id != victim.organization_id
    assert not conversation.awaiting_phone_confirmation and not contact.phones
    assert private.contact_id == victim.id and getattr(victim, bot.channel + '_id') is None
    assert private.id not in [t.id for t in bot.module._list_open_tickets(db, contact)]
    assert db.query(Notification).filter_by(type=NotificationType.CONTACT_LINK_REQUEST).count() > 0
    before = db.query(Notification).filter_by(type=NotificationType.CONTACT_LINK_REQUEST).count()
    bot.incoming(bot.event('связать телефон'))
    assert db.query(Notification).filter_by(type=NotificationType.CONTACT_LINK_REQUEST).count() == before


def test_admin_password_reset_immediately_invalidates_access_and_refresh(client, db, engineer_user):
    login = client.post('/auth/login', data={'username': engineer_user.email, 'password': 'test123'}).json()
    old = {'Authorization': 'Bearer ' + login['access_token']}
    admin = db.query(User).filter_by(role=UserRole.ADMIN).first()
    assert client.patch(f'/users/{engineer_user.id}', json={'password': 'ResetAudit123!'}, headers=headers(admin)).status_code == 200
    assert client.get('/auth/me', headers=old).status_code == 401
    assert client.post('/auth/refresh', json={'refresh_token': login['refresh_token']}).status_code == 401
    fresh = client.post('/auth/login', data={'username': engineer_user.email, 'password': 'ResetAudit123!'})
    assert fresh.status_code == 200
    assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + fresh.json()['access_token']}).status_code == 200


def test_self_password_change_renews_current_session_and_revokes_old_ones(client, engineer_user):
    login = client.post('/auth/login', data={'username': engineer_user.email, 'password': 'test123'}).json()
    old = {'Authorization': 'Bearer ' + login['access_token']}
    response = client.post('/auth/me/password', headers=old, json={'current_password': 'test123', 'new_password': 'NewAudit123!'})
    assert response.status_code == 200, response.text
    assert client.get('/auth/me', headers=old).status_code == 401
    assert client.get('/auth/me', headers={'Authorization': 'Bearer ' + response.json()['access_token']}).status_code == 200
    assert client.post('/auth/refresh', json={'refresh_token': login['refresh_token']}).status_code == 401
    assert client.post('/auth/refresh', json={'refresh_token': response.json()['refresh_token']}).status_code == 200


def test_reactivation_cannot_restore_an_old_staff_session(client, db, engineer_user):
    old = headers(engineer_user)
    admin = db.query(User).filter_by(role=UserRole.ADMIN).first()
    for active in (False, True):
        assert client.patch(f'/users/{engineer_user.id}', json={'is_active': active}, headers=headers(admin)).status_code == 200
        assert client.get('/auth/me', headers=old).status_code == 401


def test_revoked_access_cannot_return_via_jwt_password_or_fresh_magic_link(client, db, contact):
    email = 'revoked-audit@example.com'
    db.add(ContactEmail(contact_id=contact.id, email=email, is_primary=True)); db.commit()
    portal.set_password(db, contact, 'PortalAudit123!')
    old = portal_headers(contact)
    _, link = portal.issue_magic_link(db, email)
    portal.revoke_access(db, contact)
    assert client.get('/portal/me', headers=old).status_code == 401
    assert client.post('/portal/auth/login', json={'email': email, 'password': 'PortalAudit123!'}).status_code == 401
    assert portal.issue_magic_link(db, email) is None
    assert client.post('/portal/auth/magic-link/consume', params={'token': link.split('token=')[1]}).status_code == 400
    # Restoring access is an explicit staff operation; it never restores old JWTs.
    portal.set_password(db, contact, 'PortalRestored123!')
    assert client.get('/portal/me', headers=old).status_code == 401
    fresh = client.post('/portal/auth/login', json={'email': email, 'password': 'PortalRestored123!'})
    assert fresh.status_code == 200
    assert client.get('/portal/me', headers={'Authorization': 'Bearer ' + fresh.json()['access_token']}).status_code == 200


def test_portal_password_change_revokes_old_jwts_and_pending_links(client, db, contact):
    db.add(ContactEmail(contact_id=contact.id, email='portal-audit@example.com', is_primary=True)); db.commit()
    portal.set_password(db, contact, 'PortalAudit123!')
    old = portal_headers(contact)
    _, link = portal.issue_magic_link(db, 'portal-audit@example.com')
    response = client.post('/portal/me/password', headers=old, json={'current_password': 'PortalAudit123!', 'new_password': 'PortalChanged123!'})
    assert response.status_code == 200, response.text
    assert client.get('/portal/me', headers=old).status_code == 401
    assert client.get('/portal/me', headers={'Authorization': 'Bearer ' + response.json()['access_token']}).status_code == 200
    assert client.post('/portal/auth/magic-link/consume', params={'token': link.split('token=')[1]}).status_code == 400


def test_legacy_portal_session_with_deleted_credentials_is_rejected(client, contact):
    assert client.get('/portal/me', headers=portal_headers(contact)).status_code == 401


def test_revoked_generation_cannot_connect_websocket(db, engineer_user, monkeypatch):
    from app.api.routers import ws
    from app.core.security import revoke_user_sessions
    monkeypatch.setattr(ws, 'SessionLocal', lambda: SimpleNamespace(get=db.get, close=lambda: None))
    old = create_access_token(engineer_user.id, engineer_user.role.value, engineer_user.auth_version)
    assert ws._authenticate(old) == engineer_user.id
    revoke_user_sessions(db, engineer_user); db.commit()
    assert ws._authenticate(old) is None


def test_revoke_closes_existing_websockets():
    from app.services.realtime import NotificationHub
    class Socket:
        async def accept(self): pass
        async def close(self, code): self.code = code
        async def send_json(self, payload): raise AssertionError('Revoked socket must receive no notification data')
    async def check():
        hub = NotificationHub(); socket = Socket()
        await hub.connect(42, socket)
        await hub._fan_out(42, {'type': 'session_revoked'})
        assert socket.code == 1008 and 42 not in hub._connections
    asyncio.run(check())


def working(db, contact, user):
    ticket = make(db, contact, channel=Channel.PORTAL)
    ticket.assigned_engineer_id = user.id
    ticket.planned_due_at = datetime.now(timezone.utc) + timedelta(days=1)
    ticket.estimated_minutes = 60; db.commit()
    timer = time_entries.start_timer(db, ticket, user)
    timer.started_at -= timedelta(minutes=5, seconds=10); db.commit()
    return ticket, timer


@pytest.mark.parametrize('target', [TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_THIRD_PARTY, TicketStatus.RESOLVED, TicketStatus.CANCELLED])
def test_leaving_work_banks_timer_once_and_never_bills_waiting(db, contact, engineer_user, target):
    ticket, _ = working(db, contact, engineer_user)
    tickets.transition_status(db, ticket, target, engineer_user)
    assert time_entries.get_active_timer(db, engineer_user) is None
    entry = db.query(TimeEntry).filter_by(ticket_id=ticket.id).one()
    assert entry.duration_minutes == 6 and entry.is_billable
    assert time_entries.stop_timer(db, engineer_user) is None
    assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).count() == 1


def test_result_and_acceptance_stop_all_participants_timers(db, contact, engineer_user):
    ticket, _ = working(db, contact, engineer_user)
    admin = db.query(User).filter_by(role=UserRole.ADMIN).first()
    timer = time_entries.start_timer(db, ticket, admin)
    timer.started_at -= timedelta(minutes=2, seconds=5); db.commit()
    customer_acceptance.submit(db, ticket, MessageCreate(direction='outbound', channel='portal', body='Результат готов: файл и проверка в системе', request_id=uuid4()), engineer_user, [])
    assert ticket.status == TicketStatus.RESOLVED
    assert db.query(ActiveTimer).filter_by(ticket_id=ticket.id).count() == 0
    assert sorted(e.duration_minutes for e in db.query(TimeEntry).filter_by(ticket_id=ticket.id)) == [3, 6]
    customer_acceptance.decide(db, ticket, contact, ticket.resolution_message_id, True)
    assert ticket.status == TicketStatus.CLOSED and ticket.accepted_at
    assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).count() == 2


def test_failed_status_change_rolls_back_timer_and_hours(db, contact, engineer_user, monkeypatch):
    ticket, timer = working(db, contact, engineer_user)
    started = timer.started_at
    def fail(*args, **kwargs): raise RuntimeError('Simulated transaction failure')
    monkeypatch.setattr('app.services.staff_notifications.notify_status_change', fail)
    with pytest.raises(RuntimeError):
        tickets.update_ticket(db, ticket, TicketUpdate(status='waiting_customer'), engineer_user)
    db.expire_all()
    assert db.get(ActiveTimer, timer.id).started_at == started
    assert db.get(type(ticket), ticket.id).status == TicketStatus.IN_PROGRESS
    assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).count() == 0


def test_automatic_stop_can_book_hours_while_another_start_holds_user_lock(db, contact):
    # Real independent DB connections, without committing fixture data.
    # The existing admin is visible to both. The fixture timer is only visible
    # here; the other start pauses after locking the user, before ticket lookup.
    admin = db.query(User).filter_by(role=UserRole.ADMIN).first()
    ticket = make(db, contact, channel=Channel.PORTAL)
    ticket.status = TicketStatus.IN_PROGRESS
    db.add(ActiveTimer(user_id=admin.id, ticket_id=ticket.id,
                       started_at=datetime.now(timezone.utc) - timedelta(minutes=2)))
    db.commit()
    admin_id = admin.id
    locked, release = threading.Event(), threading.Event()
    failures = []
    def pause_after_lock(conn, cursor, statement, parameters, context, executemany):
        if threading.current_thread().name == 'audit-concurrent-start' and 'FROM users' in statement and 'FOR ' in statement:
            locked.set()
            if not release.wait(5): raise TimeoutError('Concurrent test did not release user lock')
    def concurrent_start():
        with SessionLocal() as other:
            try:
                time_entries.start_timer(other, SimpleNamespace(id=2_000_000_000), other.get(User, admin_id))
            except time_entries.TimerTicketNotFound:
                pass
            except Exception as exc:
                failures.append(exc)
    event.listen(engine, 'after_cursor_execute', pause_after_lock)
    thread = threading.Thread(target=concurrent_start, name='audit-concurrent-start', daemon=True)
    try:
        thread.start()
        assert locked.wait(3), 'Starting work blocked automatic timer accounting on the user FK'
        db.execute(text("SET LOCAL statement_timeout = '2s'"))
        tickets.transition_status(db, ticket, TicketStatus.WAITING_CUSTOMER, None, notify_status=False)
        assert db.query(ActiveTimer).filter_by(ticket_id=ticket.id).count() == 0
        assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).one().duration_minutes >= 2
    finally:
        release.set(); thread.join(5)
        event.remove(engine, 'after_cursor_execute', pause_after_lock)
    assert not thread.is_alive() and not failures


@pytest.mark.parametrize('minutes', [-60, -1, 0])
def test_api_rejects_nonpositive_create_and_edit(client, db, contact, engineer_user, minutes):
    ticket = make(db, contact)
    path = f'/tickets/{ticket.id}/time-entries'
    payload = {'entry_date': str(date.today()), 'duration_minutes': minutes}
    assert client.post(path, headers=headers(engineer_user), json=payload).status_code == 422
    assert db.query(TimeEntry).filter_by(ticket_id=ticket.id).count() == 0
    payload['duration_minutes'] = 1
    entry = client.post(path, headers=headers(engineer_user), json=payload)
    assert entry.status_code == 201
    assert client.patch(path + '/' + str(entry.json()['id']), headers=headers(engineer_user), json={'duration_minutes': minutes}).status_code == 422
    assert db.get(TimeEntry, entry.json()['id']).duration_minutes == 1


def test_database_rejects_negative_hours_outside_api(db, contact, engineer_user):
    ticket = make(db, contact)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(TimeEntry(ticket_id=ticket.id, engineer_id=engineer_user.id, entry_date=date.today(), duration_minutes=-1, billed_overage_minutes=-1))
        db.flush()


def test_closing_without_an_accepted_result_cannot_manufacture_statuses(db, contact):
    ticket = make(db, contact)
    with pytest.raises(ValueError): messenger_common.close_ticket_chain(db, ticket)
    assert ticket.status == TicketStatus.NEW and ticket.resolved_at is None and ticket.closed_at is None
    assert db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='status_changed').count() == 0


def test_old_close_button_requires_confirmation_and_cancels_instead_of_closing(db, contact, bot):
    ticket = make(db, contact, channel=Channel(bot.channel))
    bot.incoming(bot.event(callback=f'close:{ticket.id}'))
    db.refresh(ticket); assert ticket.status == TicketStatus.NEW and ticket.resolved_at is None
    bot.incoming(bot.event(callback=f'cancel_ticket_confirm:{ticket.id}'))
    db.refresh(ticket)
    assert ticket.status == TicketStatus.CANCELLED and ticket.accepted_at is None and ticket.csat_requested_at is None
    assert ticket.resolution_message_id is None and ticket.closed_at is None
    bot.incoming(bot.event(callback=f'cancel_ticket_confirm:{ticket.id}'))
    assert db.query(AuditLog).filter_by(entity_type='ticket', entity_id=ticket.id, action='customer_cancelled').count() == 1


def test_cancel_rechecks_owner_and_status_after_confirmation(db, contact, bot):
    other = Contact(organization_id=contact.organization_id, full_name='Other owner'); db.add(other); db.commit()
    private = make(db, other, channel=Channel(bot.channel))
    bot.incoming(bot.event(callback=f'cancel_ticket_confirm:{private.id}'))
    db.refresh(private); assert private.status == TicketStatus.NEW
    own = make(db, contact, channel=Channel(bot.channel))
    bot.incoming(bot.event(callback=f'cancel_ticket:{own.id}'))
    tickets.transition_status(db, own, TicketStatus.IN_PROGRESS, None, notify_status=False)
    tickets.transition_status(db, own, TicketStatus.RESOLVED, None, notify_status=False)
    bot.incoming(bot.event(callback=f'cancel_ticket_confirm:{own.id}'))
    db.refresh(own); assert own.status == TicketStatus.RESOLVED
