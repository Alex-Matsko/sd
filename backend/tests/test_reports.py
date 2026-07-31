"""Reports aggregation tests (services/reports.py). Report inputs are set
directly on ORM objects rather than replayed through the full SLA/CSAT
lifecycle - this suite tests the aggregation math, not the business rules
that produce those fields (already covered by test_sla.py / test_max_channel.py)."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, TicketType
from app.models.category import Category
from app.models.contact import Contact
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.ticket import TicketCreate
from app.services import reports
from app.services import tickets as tickets_service

PERIOD_FROM = date(2026, 7, 1)
PERIOD_TO = date(2026, 7, 31)
IN_PERIOD = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
OUT_OF_PERIOD = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)


def _make_ticket(db: Session, contact: Contact, **overrides) -> Ticket:
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=overrides.pop("channel", Channel.EMAIL),
        subject=overrides.pop("subject", "Тестовая заявка"),
        category_id=overrides.pop("category_id", None),
        manual_priority=overrides.pop("priority", Priority.P2),
        manual_priority_reason="test",
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    for field, value in overrides.items():
        setattr(ticket, field, value)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def test_sla_section_computes_percentages_and_violations(db: Session, contact: Contact):
    _make_ticket(db, contact, created_at=IN_PERIOD, priority=Priority.P1, sla_reaction_met=True, sla_resolution_met=True)
    bad = _make_ticket(db, contact, created_at=IN_PERIOD, priority=Priority.P1, sla_reaction_met=False, sla_resolution_met=True)
    _make_ticket(db, contact, created_at=OUT_OF_PERIOD, priority=Priority.P1, sla_reaction_met=False, sla_resolution_met=False)

    result = reports.get_overview(db, PERIOD_FROM, PERIOD_TO, organization_id=contact.organization_id)
    sla = result["sla"]

    assert sla["total"] == 2  # out-of-period ticket excluded
    assert sla["reaction_met_pct"] == 50.0
    assert sla["resolution_met_pct"] == 100.0
    violation_ids = {v["ticket_id"] for v in sla["violations"]}
    assert violation_ids == {bad.id}


def test_flow_section_groups_by_channel_and_category(db: Session, contact: Contact):
    cat = Category(name="1С")
    db.add(cat)
    db.commit()
    _make_ticket(db, contact, created_at=IN_PERIOD, channel=Channel.TELEGRAM, category_id=cat.id)
    _make_ticket(db, contact, created_at=IN_PERIOD, channel=Channel.TELEGRAM)
    _make_ticket(db, contact, created_at=IN_PERIOD, channel=Channel.EMAIL)

    flow = reports.get_overview(db, PERIOD_FROM, PERIOD_TO, organization_id=contact.organization_id)["flow"]
    channel_counts = {row["channel"]: row["count"] for row in flow["by_channel"]}
    assert channel_counts["telegram"] == 2
    assert channel_counts["email"] == 1
    category_counts = {row["category"]: row["count"] for row in flow["by_category"]}
    assert category_counts["1С"] == 1
    assert category_counts["Без категории"] == 2


def test_workload_section_splits_billable_and_counts_resolved(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact, created_at=IN_PERIOD, assigned_engineer_id=engineer_user.id, resolved_at=IN_PERIOD)
    db.add(TimeEntry(ticket_id=ticket.id, engineer_id=engineer_user.id, entry_date=date(2026, 7, 15), duration_minutes=60, is_billable=True))
    db.add(TimeEntry(ticket_id=ticket.id, engineer_id=engineer_user.id, entry_date=date(2026, 7, 16), duration_minutes=20, is_billable=False))
    db.commit()

    workload = reports.get_overview(db, PERIOD_FROM, PERIOD_TO, organization_id=contact.organization_id)["workload"]
    row = next(r for r in workload if r["engineer_id"] == engineer_user.id)
    assert row["billable_minutes"] == 60
    assert row["non_billable_minutes"] == 20
    assert row["resolved_count"] == 1


def test_csat_section_averages_and_groups(db: Session, contact: Contact, engineer_user: User):
    _make_ticket(db, contact, created_at=IN_PERIOD, assigned_engineer_id=engineer_user.id, csat_rating=5, csat_rated_at=IN_PERIOD)
    _make_ticket(db, contact, created_at=IN_PERIOD, assigned_engineer_id=engineer_user.id, csat_rating=3, csat_rated_at=IN_PERIOD)
    _make_ticket(db, contact, created_at=IN_PERIOD, csat_rating=1, csat_rated_at=OUT_OF_PERIOD)  # excluded

    csat = reports.get_overview(db, PERIOD_FROM, PERIOD_TO, organization_id=contact.organization_id)["csat"]
    assert csat["count"] == 2
    assert csat["average"] == 4.0
    by_eng = {row["label"]: row for row in csat["by_engineer"]}
    assert by_eng[engineer_user.full_name]["average"] == 4.0
    assert by_eng[engineer_user.full_name]["count"] == 2


def test_backlog_aging_buckets_open_tickets_by_age(db: Session, contact: Contact):
    now = datetime.now(timezone.utc)
    _make_ticket(db, contact, created_at=now - timedelta(hours=5))
    _make_ticket(db, contact, created_at=now - timedelta(days=2))
    _make_ticket(db, contact, created_at=now - timedelta(days=10))

    aging = reports.get_overview(db, PERIOD_FROM, PERIOD_TO, organization_id=contact.organization_id)["backlog_aging"]
    by_bucket = {row["bucket"]: row["count"] for row in aging}
    assert by_bucket["0–1 дн."] == 1
    assert by_bucket["1–3 дн."] == 1
    assert by_bucket["7+ дн."] == 1


def test_organization_filter_scopes_results(db: Session, contact: Contact):
    other_org = Organization(name="Другая организация")
    db.add(other_org)
    db.flush()
    other_contact = Contact(organization_id=other_org.id, full_name="Другой контакт")
    db.add(other_contact)
    db.commit()

    _make_ticket(db, contact, created_at=IN_PERIOD)
    _make_ticket(db, other_contact, created_at=IN_PERIOD)

    scoped = reports.get_overview(db, PERIOD_FROM, PERIOD_TO, organization_id=contact.organization_id)
    assert scoped["sla"]["total"] == 1
    assert scoped["flow"]["total"] == 1
