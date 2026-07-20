from datetime import date

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry


def _package_minutes_used(
    db: Session, organization_id: int, year: int, month: int, exclude_entry_id: int | None = None
) -> int:
    query = (
        db.query(func.coalesce(func.sum(TimeEntry.billed_package_minutes), 0))
        .join(Ticket, Ticket.id == TimeEntry.ticket_id)
        .filter(
            Ticket.organization_id == organization_id,
            extract("year", TimeEntry.entry_date) == year,
            extract("month", TimeEntry.entry_date) == month,
        )
    )
    if exclude_entry_id is not None:
        query = query.filter(TimeEntry.id != exclude_entry_id)
    return int(query.scalar() or 0)


def split_time_entry(
    db: Session,
    contract: Contract | None,
    entry_date: date,
    duration_minutes: int,
    is_billable: bool,
    exclude_entry_id: int | None = None,
) -> tuple[int, int]:
    """Proportional package/overage split (docs/decisions.md: "Биллинг на
    границе пакета часов"). Non-billable entries never consume the package or
    generate overage. Entries logged with no active contract have no package to
    consume against, so the whole duration is reported as overage (informational
    only - there is no overage rate to apply without a contract).

    `exclude_entry_id` must be passed when recomputing an *existing* entry being
    edited, so its own already-stored package minutes aren't double-counted
    against the remaining balance."""
    if not is_billable:
        return 0, 0
    if contract is None:
        return 0, duration_minutes

    package_total_minutes = int(round(float(contract.included_hours_per_month) * 60))
    used_minutes = _package_minutes_used(
        db, contract.organization_id, entry_date.year, entry_date.month, exclude_entry_id
    )
    remaining = max(package_total_minutes - used_minutes, 0)

    package_minutes = min(duration_minutes, remaining)
    overage_minutes = duration_minutes - package_minutes
    return package_minutes, overage_minutes


def get_organization_usage(db: Session, organization_id: int, contract: Contract, year: int, month: int) -> dict:
    """Real-time package usage for an organization in a given month (section 5)."""
    package_total_minutes = int(round(float(contract.included_hours_per_month) * 60))
    package_used_minutes = _package_minutes_used(db, organization_id, year, month)

    overage_minutes = (
        db.query(func.coalesce(func.sum(TimeEntry.billed_overage_minutes), 0))
        .join(Ticket, Ticket.id == TimeEntry.ticket_id)
        .filter(
            Ticket.organization_id == organization_id,
            extract("year", TimeEntry.entry_date) == year,
            extract("month", TimeEntry.entry_date) == month,
        )
        .scalar()
    )
    overage_minutes = int(overage_minutes or 0)
    overage_cost = round((overage_minutes / 60) * float(contract.overage_rate_per_hour), 2)

    return {
        "organization_id": organization_id,
        "year": year,
        "month": month,
        "package_total_minutes": package_total_minutes,
        "package_used_minutes": min(package_used_minutes, package_total_minutes),
        "package_remaining_minutes": max(package_total_minutes - package_used_minutes, 0),
        "overage_minutes": overage_minutes,
        "overage_cost": overage_cost,
    }
