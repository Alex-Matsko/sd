from datetime import date

from app.core.enums import Channel, TicketStatus, TicketType
from app.models.ticket import Ticket
from app.services import billing


def _ticket(db, organization, contact, contract, tariff):
    ticket = Ticket(
        type=TicketType.INCIDENT,
        channel=Channel.PORTAL,
        subject="Test",
        organization_id=organization.id,
        contact_id=contact.id,
        contract_id=contract.id if contract else None,
        tariff_id=tariff.id,
        has_no_active_contract=contract is None,
        priority="P3",
        status=TicketStatus.NEW,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def test_entry_fully_within_package(db, organization, contact, active_contract, default_tariff):
    ticket = _ticket(db, organization, contact, active_contract, default_tariff)
    package_minutes, overage_minutes = billing.split_time_entry(
        db, active_contract, date(2026, 1, 15), duration_minutes=60, is_billable=True
    )
    assert (package_minutes, overage_minutes) == (60, 0)


def test_entry_crossing_package_boundary_splits_proportionally(db, organization, contact, active_contract, default_tariff):
    """docs/decisions.md: "Биллинг на границе пакета часов" - the entry that
    crosses the remaining balance is split, not dumped entirely into one
    bucket."""
    ticket = _ticket(db, organization, contact, active_contract, default_tariff)
    # included_hours_per_month=10 -> 600 minutes. Use up 540 minutes first.
    billing_service_add(db, ticket, active_contract, date(2026, 1, 5), 540)

    package_minutes, overage_minutes = billing.split_time_entry(
        db, active_contract, date(2026, 1, 20), duration_minutes=180, is_billable=True
    )
    assert (package_minutes, overage_minutes) == (60, 120)


def test_entry_after_package_exhausted_is_pure_overage(db, organization, contact, active_contract, default_tariff):
    ticket = _ticket(db, organization, contact, active_contract, default_tariff)
    billing_service_add(db, ticket, active_contract, date(2026, 1, 5), 600)

    package_minutes, overage_minutes = billing.split_time_entry(
        db, active_contract, date(2026, 1, 20), duration_minutes=90, is_billable=True
    )
    assert (package_minutes, overage_minutes) == (0, 90)


def test_next_month_resets_the_package_balance(db, organization, contact, active_contract, default_tariff):
    ticket = _ticket(db, organization, contact, active_contract, default_tariff)
    billing_service_add(db, ticket, active_contract, date(2026, 1, 5), 600)

    package_minutes, overage_minutes = billing.split_time_entry(
        db, active_contract, date(2026, 2, 1), duration_minutes=60, is_billable=True
    )
    assert (package_minutes, overage_minutes) == (60, 0)


def test_non_billable_entry_never_consumes_package_or_overage(db, organization, contact, active_contract, default_tariff):
    package_minutes, overage_minutes = billing.split_time_entry(
        db, active_contract, date(2026, 1, 20), duration_minutes=120, is_billable=False
    )
    assert (package_minutes, overage_minutes) == (0, 0)


def test_billable_entry_without_contract_is_reported_as_overage(db):
    package_minutes, overage_minutes = billing.split_time_entry(
        db, None, date(2026, 1, 20), duration_minutes=90, is_billable=True
    )
    assert (package_minutes, overage_minutes) == (0, 90)


def test_organization_usage_reflects_logged_entries(db, organization, contact, active_contract, default_tariff):
    ticket = _ticket(db, organization, contact, active_contract, default_tariff)
    billing_service_add(db, ticket, active_contract, date(2026, 3, 5), 540)
    billing_service_add(db, ticket, active_contract, date(2026, 3, 20), 180)  # 60 package + 120 overage

    usage = billing.get_organization_usage(db, organization.id, active_contract, 2026, 3)
    assert usage["package_used_minutes"] == 600
    assert usage["package_remaining_minutes"] == 0
    assert usage["overage_minutes"] == 120
    assert usage["overage_cost"] == round((120 / 60) * float(active_contract.overage_rate_per_hour), 2)


def billing_service_add(db, ticket, contract, entry_date, duration_minutes):
    """Persists a TimeEntry the way the create_time_entry service would,
    without pulling in the full service module (kept local to this test file
    to avoid depending on User/engineer fixtures for pure billing-math tests)."""
    from app.models.time_entry import TimeEntry

    package_minutes, overage_minutes = billing.split_time_entry(
        db, contract, entry_date, duration_minutes, is_billable=True
    )
    entry = TimeEntry(
        ticket_id=ticket.id,
        engineer_id=_ensure_engineer(db).id,
        entry_date=entry_date,
        duration_minutes=duration_minutes,
        is_billable=True,
        billed_package_minutes=package_minutes,
        billed_overage_minutes=overage_minutes,
    )
    db.add(entry)
    db.commit()
    return entry


def _ensure_engineer(db):
    from app.core.enums import UserRole
    from app.core.security import hash_password
    from app.models.user import User

    user = db.query(User).filter(User.email == "billing.fixture@o-horizons.com").first()
    if user is None:
        user = User(
            full_name="Billing Fixture",
            email="billing.fixture@o-horizons.com",
            password_hash=hash_password("x"),
            role=UserRole.ENGINEER,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
