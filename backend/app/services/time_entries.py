import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import TicketStatus
from app.models.active_timer import ActiveTimer
from app.models.contract import Contract
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.time_entry import TimeEntryCreate, TimeEntryUpdate
from app.services import audit, billing


def create_time_entry(db: Session, ticket: Ticket, payload: TimeEntryCreate, engineer: User, *, commit=True) -> TimeEntry:
    if payload.duration_minutes <= 0:
        raise ValueError("Трудозатраты должны быть больше нуля")
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
    if commit:
        db.commit()
        db.refresh(entry)
    return entry


# Threshold in *seconds*, checked before rounding. Comparing the rounded
# minutes instead would never trigger: ceil() turns even half a second into
# one minute, so a mis-click would still book an entry.
MIN_TIMER_SECONDS = 60

# Подпись автоматического списания. Запись, созданная таймером, ничем иначе
# не отличается от введённой руками — а разница важна и инженеру, который
# правит своё время, и при разборе счёта с клиентом.
TIMER_COMMENT = "По таймеру"


class TimerTicketNotFound(ValueError):
    pass


def start_timer(db: Session, ticket: Ticket, engineer: User, plan=None) -> ActiveTimer:
    """Start work, bank the previous timer and change status atomically.

    A second click keeps elapsed time. User and ticket locks serialize timer
    switches and prevent starting work from an obsolete status/access check.
    """
    from app.services import ticket_access, tickets
    from app.services.channel_queue import DeferredCommitSession

    ticket_id, user_id = ticket.id, engineer.id
    # NO KEY UPDATE serializes this user's timer actions while allowing the
    # FK checks needed to bank their timer during a concurrent status change.
    db.query(User.id).filter(User.id == user_id).with_for_update(key_share=True).one()
    with DeferredCommitSession(bind=db.connection(), join_transaction_mode="create_savepoint") as unit:
        previous = unit.query(ActiveTimer).filter_by(user_id=user_id).first()
        # Lock both tickets in a stable order when switching. No timer row is
        # locked before its ticket: automatic stop follows the same order.
        ids = {ticket_id} | ({previous.ticket_id} if previous else set())
        locked = unit.query(Ticket).filter(Ticket.id.in_(ids)).order_by(Ticket.id).with_for_update().all()
        current = next((t for t in locked if t.id == ticket_id), None)
        actor = unit.get(User, user_id)
        if current is None or not ticket_access.can_see(unit, actor, current):
            raise TimerTicketNotFound("Заявка не найдена")
        status = TicketStatus(current.status)
        if status in (TicketStatus.CLOSED, TicketStatus.CANCELLED):
            raise ValueError("Нельзя начать работу по закрытой или отменённой заявке")

        from app.services import work_planning
        plan_changed = work_planning.apply(unit, current, plan, actor) if plan is not None else False
        work_planning.require_plan(current)
        if plan_changed and status == TicketStatus.IN_PROGRESS:
            work_planning.notify_plan(unit, current)
        timer = unit.query(ActiveTimer).filter(ActiveTimer.user_id == user_id).populate_existing().with_for_update().first()
        if timer is not None and timer.ticket_id != ticket_id:
            stop_timer(unit, actor, comment="Автоматически остановлен при запуске таймера по другой заявке")
            timer = None
        if status != TicketStatus.IN_PROGRESS:
            tickets.transition_status(unit, current, TicketStatus.IN_PROGRESS, actor)
        if timer is None:
            timer = ActiveTimer(user_id=user_id, ticket_id=ticket_id, started_at=datetime.now(timezone.utc))
            unit.add(timer)
            unit.flush()
        timer_id = timer.id
        Session.commit(unit)
    db.commit()
    db.expire_all()
    return db.get(ActiveTimer, timer_id)


def stop_timer(db: Session, engineer: User, comment: str | None = None) -> TimeEntry | None:
    """Stops the running timer and books the elapsed minutes.

    Anything under a minute is dropped rather than logged as a zero-minute
    entry - a mis-click shouldn't leave a row in the client's billing report.
    Elapsed time is rounded up, so 90 seconds of work bills as 2 minutes
    rather than 1."""
    db.query(User.id).filter(User.id == engineer.id).with_for_update(key_share=True).one()
    timer = db.query(ActiveTimer).filter_by(user_id=engineer.id).first()
    if timer is None:
        return None
    ticket = db.query(Ticket).filter_by(id=timer.ticket_id).with_for_update().first()
    timer = db.query(ActiveTimer).filter_by(user_id=engineer.id).populate_existing().with_for_update().first()
    if timer is None or ticket is None:
        return None
    entry = _bank_timer(db, ticket, timer, datetime.now(timezone.utc), comment or TIMER_COMMENT)
    db.commit()
    if entry is not None:
        db.refresh(entry)
    return entry


def _bank_timer(db, ticket, timer, stopped_at, comment):
    # Old releases could leave timers on completed tickets. Never bill time
    # after their recorded completion when such a timer is eventually stopped.
    if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        cutoff = ticket.resolved_at or ticket.closed_at
        if cutoff is not None:
            stopped_at = min(stopped_at, cutoff)
    seconds = (stopped_at - timer.started_at).total_seconds()
    db.delete(timer)
    if seconds < MIN_TIMER_SECONDS:
        db.flush()
        return None
    return create_time_entry(db, ticket, TimeEntryCreate(
        entry_date=stopped_at.date(), duration_minutes=math.ceil(seconds / 60), comment=comment,
    ), db.get(User, timer.user_id), commit=False)


def stop_ticket_timers(db, ticket, stopped_at):
    """Bank every participant's timer in the status transaction, without an
    inner commit. The caller holds the ticket lock; no user lock is needed."""
    timers = db.query(ActiveTimer).filter_by(ticket_id=ticket.id).order_by(ActiveTimer.user_id).populate_existing().with_for_update().all()
    for timer in timers:
        _bank_timer(db, ticket, timer, stopped_at, "По таймеру — автоматически при смене статуса")


def get_active_timer(db: Session, engineer: User) -> ActiveTimer | None:
    return db.query(ActiveTimer).filter(ActiveTimer.user_id == engineer.id).first()


def update_time_entry(db: Session, entry: TimeEntry, payload: TimeEntryUpdate, actor: User) -> TimeEntry:
    ticket = db.get(Ticket, entry.ticket_id)
    contract = db.get(Contract, ticket.contract_id) if ticket.contract_id else None

    duration_minutes = payload.duration_minutes if payload.duration_minutes is not None else entry.duration_minutes
    if duration_minutes <= 0:
        raise ValueError("Трудозатраты должны быть больше нуля")
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


def delete_time_entry(db: Session, entry: TimeEntry, actor: User) -> None:
    """Убирает списание вместе со следом в истории заявки.

    Пересчитывать раскладку у остальных записей не нужно: пакет считается
    суммой существующих записей, поэтому освободившиеся минуты сами вернутся
    в остаток при следующем списании. Уже посчитанные записи сохраняют свою
    раскладку — так же, как при изменении договора задним числом
    (docs/decisions.md, «Биллинг на границе пакета часов»).
    """
    audit.record(
        db,
        entity_type="time_entry",
        entity_id=entry.id,
        action="deleted",
        user_id=actor.id,
        changes={"duration_minutes": entry.duration_minutes, "is_billable": entry.is_billable},
    )
    db.delete(entry)
    db.commit()
