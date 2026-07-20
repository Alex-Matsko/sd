from sqlalchemy.orm import Session

from app.models.contract import Contract
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.time_entry import TimeEntryCreate, TimeEntryUpdate
from app.services import audit, billing


def create_time_entry(db: Session, ticket: Ticket, payload: TimeEntryCreate, engineer: User) -> TimeEntry:
    contract = db.get(Contract, ticket.contract_id) if ticket.contract_id else None
    package_minutes, overage_minutes = billing.split_time_entry(
        db, contract, payload.entry_date, payload.duration_minutes, payload.is_billable
    )
    entry = TimeEntry(
        ticket_id=ticket.id,
        engineer_id=engineer.id,
        entry_date=payload.entry_date,
        duration_minutes=payload.duration_minutes,
        comment=payload.comment,
        is_billable=payload.is_billable,
        billed_package_minutes=package_minutes,
        billed_overage_minutes=overage_minutes,
    )
    db.add(entry)
    db.flush()
    audit.record(
        db,
        entity_type="time_entry",
        entity_id=entry.id,
        action="created",
        user_id=engineer.id,
        changes={"duration_minutes": payload.duration_minutes, "is_billable": payload.is_billable},
    )
    db.commit()
    db.refresh(entry)
    return entry


def update_time_entry(db: Session, entry: TimeEntry, payload: TimeEntryUpdate, actor: User) -> TimeEntry:
    ticket = db.get(Ticket, entry.ticket_id)
    contract = db.get(Contract, ticket.contract_id) if ticket.contract_id else None

    duration_minutes = payload.duration_minutes if payload.duration_minutes is not None else entry.duration_minutes
    entry_date = payload.entry_date if payload.entry_date is not None else entry.entry_date
    is_billable = payload.is_billable if payload.is_billable is not None else entry.is_billable

    if payload.comment is not None:
        entry.comment = payload.comment

    recompute = (
        payload.duration_minutes is not None or payload.entry_date is not None or payload.is_billable is not None
    )
    entry.duration_minutes = duration_minutes
    entry.entry_date = entry_date
    entry.is_billable = is_billable

    if recompute:
        package_minutes, overage_minutes = billing.split_time_entry(
            db, contract, entry_date, duration_minutes, is_billable, exclude_entry_id=entry.id
        )
        entry.billed_package_minutes = package_minutes
        entry.billed_overage_minutes = overage_minutes

    db.add(entry)
    audit.record(
        db,
        entity_type="time_entry",
        entity_id=entry.id,
        action="updated",
        user_id=actor.id,
        changes={"duration_minutes": duration_minutes, "is_billable": is_billable},
    )
    db.commit()
    db.refresh(entry)
    return entry
