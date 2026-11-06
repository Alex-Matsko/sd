"""Regressions found during the project/interface review."""
from datetime import datetime, timedelta, timezone

import pytest
from app.models.user import User
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.routers.reports import _period
from app.api.routers.tickets import get_ticket_stats, list_tickets
from app.core.enums import AssetType, Channel, Priority, TicketStatus, TicketType, UserRole
from app.db import get_db
from app.main import app
from app.models.asset import Asset
from app.models.organization import Organization
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import tickets


@pytest.fixture()
def admin_user(db):
    return db.query(User).filter(User.role == UserRole.ADMIN).first()


def make_ticket(db, contact, **overrides):
    return tickets.create_ticket(db, TicketCreate(
        contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PHONE,
        subject="Проверка очереди", manual_priority=Priority.P3, manual_priority_reason="test",
        **overrides,
    ), actor=None)


def test_open_scope_applies_before_pagination(db, contact, admin_user):
    active = make_ticket(db, contact)
    archived = make_ticket(db, contact)
    archived.status = TicketStatus.CLOSED
    db.commit()
    response = Response()
    result = list_tickets(response, organization_id=contact.organization_id, open_only=True,
                          limit=1, db=db, actor=admin_user)
    assert [t.id for t in result] == [active.id]
    assert response.headers["X-Total-Count"] == "1"


def test_overdue_link_matches_dashboard_and_ignores_paused_timers(db, contact, admin_user):
    overdue = make_ticket(db, contact)
    paused = make_ticket(db, contact)
    for ticket in (overdue, paused):
        ticket.sla_resolution_due_at = datetime.now(timezone.utc) - timedelta(hours=1)
        ticket.sla_resolution_met = None
    paused.sla_paused_at = datetime.now(timezone.utc)
    db.commit()
    response = Response()
    result = list_tickets(response, overdue=True, db=db, actor=admin_user)
    ids = {t.id for t in result}
    assert overdue.id in ids and paused.id not in ids
    assert int(response.headers["X-Total-Count"]) == get_ticket_stats(db=db, actor=admin_user)["overdue"]


@pytest.mark.parametrize("path", ["/reports/overview", "/reports/overview.xlsx", "/client-reports",
                                   "/client-reports/1", "/client-reports/1/pdf", "/client-reports/1/xlsx"])
def test_engineer_cannot_bypass_ticket_visibility_through_reports(db, engineer_user, path):
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: engineer_user
    try:
        with TestClient(app) as client:
            assert client.get(path).status_code == 403
    finally:
        app.dependency_overrides = old


def test_report_rejects_reversed_period():
    from datetime import date
    with pytest.raises(HTTPException) as exc:
        _period(date(2026, 11, 2), date(2026, 11, 1))
    assert exc.value.status_code == 400


def test_asset_from_another_organization_is_rejected_on_create_and_update(db, contact):
    other = Organization(name="Другая организация для проверки актива")
    db.add(other)
    db.flush()
    asset = Asset(name="Чужой сервер", type=AssetType.SERVER, organization_id=other.id)
    db.add(asset)
    db.commit()
    with pytest.raises(ValueError, match="Актив"):
        make_ticket(db, contact, asset_id=asset.id)
    ticket = make_ticket(db, contact)
    with pytest.raises(ValueError, match="Актив"):
        tickets.update_ticket(db, ticket, TicketUpdate(asset_id=asset.id, status=TicketStatus.IN_PROGRESS), actor=None)
    assert ticket.status != TicketStatus.IN_PROGRESS
    assert ticket.asset_id is None


def test_browser_can_read_pagination_headers_across_origins(db, admin_user):
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        with TestClient(app) as client:
            result = client.get('/tickets', headers={'Origin': 'http://localhost:8081'})
            assert result.status_code == 200
            assert 'x-total-count' in result.headers['access-control-expose-headers'].lower()
    finally:
        app.dependency_overrides = old


def test_contact_duplicate_email_is_a_conflict_not_a_server_error(db, organization, admin_user):
    from app.api.routers.contacts import create_contact
    from app.schemas.contact import ContactCreate
    first = create_contact(ContactCreate(organization_id=organization.id, full_name="Первый контакт",
                                        emails=["duplicate@example.org", " Duplicate@EXAMPLE.org "]), db=db, _=admin_user)
    assert len(first.emails) == 1
    with pytest.raises(HTTPException) as exc:
        create_contact(ContactCreate(organization_id=organization.id, full_name="Дубликат",
                                     emails=["duplicate@example.org"]), db=db, _=admin_user)
    assert exc.value.status_code == 409


def test_board_keeps_resolved_work_but_excludes_archived_before_limit(db, contact, admin_user):
    resolved = make_ticket(db, contact)
    resolved.status = TicketStatus.RESOLVED
    archived = make_ticket(db, contact)
    archived.status = TicketStatus.CLOSED
    db.commit()
    response = Response()
    result = list_tickets(response, organization_id=contact.organization_id, exclude_archived=True,
                          limit=1, db=db, actor=admin_user)
    assert [ticket.id for ticket in result] == [resolved.id]
    assert response.headers['X-Total-Count'] == '1'


def test_dashboard_uses_viewers_day_for_deadlines_and_week_flow(db, contact, admin_user, monkeypatch):
    from app.api.routers import tickets as router
    first = make_ticket(db, contact)
    second = make_ticket(db, contact)
    fixed_now = datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(router, 'datetime', Clock)
    before = get_ticket_stats(db=db, actor=admin_user, tz='Europe/Istanbul')['at_risk_today']
    for ticket in (first, second):
        ticket.created_at = fixed_now
    first.sla_resolution_due_at = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
    second.sla_resolution_due_at = datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc)
    db.commit()
    stats = get_ticket_stats(db=db, actor=admin_user, tz='Europe/Istanbul')
    assert stats['week_flow'][-1]['date'] == '2026-11-07'
    assert stats['week_flow'][-1]['created'] == 2
    assert stats['at_risk_today'] == before + 1
