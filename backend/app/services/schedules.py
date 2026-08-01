"""Recurring planned tickets (по запросу заказчика, вне исходного ТЗ).

The sweep runs on the worker's normal tick. A schedule produces an ordinary
ticket through `tickets_service.create_ticket`, so SLA deadlines, routing,
billing and reporting behave exactly as they do for a ticket raised any
other way - this is a source of tickets, not a second kind of ticket.
"""

import calendar
import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import Channel, ScheduleCadence
from app.models.ticket import Ticket
from app.models.ticket_schedule import TicketSchedule
from app.schemas.ticket import TicketCreate
from app.services import tickets as tickets_service

logger = logging.getLogger("app.schedules")

_CADENCE_MONTHS = {ScheduleCadence.MONTHLY: 1, ScheduleCadence.QUARTERLY: 3}


def _add_months(value: date, months: int) -> date:
    """Month arithmetic that survives short months: the 31st of January plus
    one month is the 28th/29th of February, not an invalid date - and the
    schedule keeps its intended day-of-month for later months rather than
    permanently drifting to the 28th."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def compute_next_run(schedule: TicketSchedule, after: date) -> date:
    """First occurrence strictly after `after`, honouring the schedule's
    preferred weekday/day-of-month."""
    cadence = ScheduleCadence(schedule.cadence)

    if cadence == ScheduleCadence.DAILY:
        return date.fromordinal(after.toordinal() + 1)

    if cadence == ScheduleCadence.WEEKLY:
        target = schedule.day_of_week if schedule.day_of_week is not None else after.weekday()
        days_ahead = (target - after.weekday()) % 7 or 7
        return date.fromordinal(after.toordinal() + days_ahead)

    months = _CADENCE_MONTHS[cadence]
    if schedule.day_of_month is None:
        return _add_months(after, months)
    # Anchor on the requested day of month, clamped to the target month.
    anchored = date(after.year, after.month, min(schedule.day_of_month, calendar.monthrange(after.year, after.month)[1]))
    if anchored > after:
        return anchored
    nxt = _add_months(date(after.year, after.month, 1), months)
    return date(nxt.year, nxt.month, min(schedule.day_of_month, calendar.monthrange(nxt.year, nxt.month)[1]))


def run_due_schedules(db: Session, today: date | None = None) -> int:
    """One sweep: create a ticket for every active schedule that has come due.

    A schedule that fell behind (worker was down for a week) fires once and
    is rescheduled forward from today, rather than back-filling every missed
    occurrence - a burst of stale maintenance tickets helps nobody."""
    today = today or datetime.now(timezone.utc).date()
    due = (
        db.query(TicketSchedule)
        .filter(TicketSchedule.is_active.is_(True), TicketSchedule.next_run_on <= today)
        .all()
    )

    created = 0
    for schedule in due:
        try:
            ticket = _create_from_schedule(db, schedule)
        except Exception:
            logger.exception("Расписание %s: не удалось создать заявку", schedule.id)
            # Still move the schedule forward - otherwise a permanently broken
            # schedule (deleted contact, say) retries on every single sweep.
            schedule.next_run_on = compute_next_run(schedule, today)
            db.add(schedule)
            db.commit()
            continue

        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.next_run_on = compute_next_run(schedule, today)
        db.add(schedule)
        db.commit()
        created += 1
        logger.info("Расписание %s: создана заявка %s", schedule.id, ticket.display_number)
    return created


def _create_from_schedule(db: Session, schedule: TicketSchedule) -> Ticket:
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=schedule.contact_id,
            type=schedule.type,
            channel=Channel.PORTAL,
            subject=schedule.subject,
            category_id=schedule.category_id,
            manual_priority=schedule.priority,
            manual_priority_reason=f"Плановая заявка по расписанию «{schedule.name}»",
            initial_message=schedule.body,
        ),
        actor=None,
    )
    # An explicit engineer on the schedule wins over routing rules: planned
    # work is usually assigned to whoever owns that client's infrastructure.
    if schedule.assigned_engineer_id is not None:
        ticket.assigned_engineer_id = schedule.assigned_engineer_id
        db.add(ticket)
        db.commit()
    return ticket
