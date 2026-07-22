"""Stage 3 SLA engine tests: working-time calendar math, deadline lifecycle
(pause/resume, first response, resolve), 75%/100% escalations with dedupe, and
priority-change recompute. Time-sensitive scenarios pin `created_at`/`now` to
fixed moments so results don't depend on when the suite runs."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.enums import (
    Channel,
    ImpactUrgencyLevel,
    MessageDirection,
    NotificationType,
    Priority,
    TicketStatus,
    TicketType,
)
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.team import Team
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import messages as messages_service
from app.services import sla
from app.services import tickets as tickets_service
from app.services.calendar_math import CalendarSpec, add_working_minutes, working_minutes_between

MSK = ZoneInfo("Europe/Moscow")

# Mon-Fri 09:00-18:00 MSK, Friday 2026-06-12 (День России) is a holiday.
SPEC_5X8 = CalendarSpec(
    tz=MSK,
    is_24x7=False,
    windows={wd: [(time(9, 0), time(18, 0))] for wd in range(5)},
    holidays=frozenset({date(2026, 6, 12)}),
)
SPEC_24X7 = CalendarSpec(tz=MSK, is_24x7=True)


def msk(*args) -> datetime:
    return datetime(*args, tzinfo=MSK)


# --- calendar math -----------------------------------------------------------


def test_24x7_math_is_plain_arithmetic():
    start = msk(2026, 7, 21, 10, 0)
    assert add_working_minutes(SPEC_24X7, start, 90) == start + timedelta(minutes=90)
    assert working_minutes_between(SPEC_24X7, start, start + timedelta(hours=48)) == 48 * 60


def test_add_within_one_working_day():
    assert add_working_minutes(SPEC_5X8, msk(2026, 7, 21, 10, 0), 60) == msk(2026, 7, 21, 11, 0)


def test_add_rolls_over_to_next_morning():
    assert add_working_minutes(SPEC_5X8, msk(2026, 7, 21, 17, 30), 60) == msk(2026, 7, 22, 9, 30)


def test_add_skips_weekend():
    # Friday 17:00 + 2 working hours -> Monday 10:00
    assert add_working_minutes(SPEC_5X8, msk(2026, 7, 24, 17, 0), 120) == msk(2026, 7, 27, 10, 0)


def test_add_skips_holiday_and_weekend():
    # Thursday 2026-06-11 17:00 + 2h; Friday 12.06 is a holiday -> Monday 15.06 10:00
    assert add_working_minutes(SPEC_5X8, msk(2026, 6, 11, 17, 0), 120) == msk(2026, 6, 15, 10, 0)


def test_add_before_window_starts_at_opening():
    assert add_working_minutes(SPEC_5X8, msk(2026, 7, 21, 7, 0), 30) == msk(2026, 7, 21, 9, 30)


def test_add_on_weekend_starts_monday():
    assert add_working_minutes(SPEC_5X8, msk(2026, 7, 25, 12, 0), 30) == msk(2026, 7, 27, 9, 30)


def test_between_clips_to_windows():
    assert working_minutes_between(SPEC_5X8, msk(2026, 7, 21, 10, 0), msk(2026, 7, 21, 12, 0)) == 120
    # Tue 17:00 -> Wed 10:00: one hour Tuesday evening + one hour Wednesday morning
    assert working_minutes_between(SPEC_5X8, msk(2026, 7, 21, 17, 0), msk(2026, 7, 22, 10, 0)) == 120
    # Entire weekend contributes nothing
    assert working_minutes_between(SPEC_5X8, msk(2026, 7, 24, 18, 0), msk(2026, 7, 27, 9, 0)) == 0
    assert working_minutes_between(SPEC_5X8, msk(2026, 7, 21, 12, 0), msk(2026, 7, 21, 12, 0)) == 0


def test_calendar_without_windows_degrades_to_24x7():
    empty = CalendarSpec(tz=MSK, is_24x7=False)
    start = msk(2026, 7, 21, 10, 0)
    assert add_working_minutes(empty, start, 45) == start + timedelta(minutes=45)


# --- ticket lifecycle --------------------------------------------------------

# Fixed anchor: Tuesday 2026-07-21 10:00 MSK. Default tariff P1 = 30/240 min on
# the seeded 5x8 calendar -> reaction due 10:30 MSK, resolution due 14:00 MSK.
ANCHOR = msk(2026, 7, 21, 10, 0)


def _make_ticket(db: Session, contact: Contact, anchored: bool = True, **overrides) -> Ticket:
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.PORTAL,
        subject="Сервер недоступен",
        impact=ImpactUrgencyLevel.HIGH,
        urgency=ImpactUrgencyLevel.HIGH,
        **overrides,
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)
    if anchored:
        ticket.created_at = ANCHOR
        sla.set_initial_deadlines(db, ticket)
        db.commit()
        db.refresh(ticket)
    return ticket


def test_deadlines_set_on_create(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact)
    assert ticket.priority == Priority.P1
    assert ticket.sla_reaction_due_at == msk(2026, 7, 21, 10, 30)
    assert ticket.sla_resolution_due_at == msk(2026, 7, 21, 14, 0)


def test_first_outbound_message_fixes_reaction_met(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact, anchored=False)
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Взяли в работу"), author_user=engineer_user
    )
    db.refresh(ticket)
    assert ticket.first_response_at is not None
    assert ticket.sla_reaction_met is True


def test_late_first_response_marks_reaction_violated(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact)  # reaction due fixed at 10:30 MSK 2026-07-21 (in the past)
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Поздний ответ"), author_user=engineer_user
    )
    db.refresh(ticket)
    assert ticket.sla_reaction_met is False


def test_pause_and_resume_shift_resolution_deadline(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact)
    # Paused 11:00 -> 13:00 the same working day: 120 working minutes on hold.
    ticket.sla_paused_at = msk(2026, 7, 21, 11, 0)
    sla.apply_resume(db, ticket, resumed_at=msk(2026, 7, 21, 13, 0))
    db.commit()
    db.refresh(ticket)
    assert ticket.sla_paused_working_minutes_total == 120
    # 240 + 120 working minutes from 10:00 Tuesday -> 16:00 the same day.
    assert ticket.sla_resolution_due_at == msk(2026, 7, 21, 16, 0)
    assert ticket.sla_reaction_due_at == msk(2026, 7, 21, 10, 30)  # reaction timer never pauses


def test_pause_over_weekend_costs_no_working_time(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact)
    ticket.sla_paused_at = msk(2026, 7, 24, 18, 0)  # Friday close of business
    sla.apply_resume(db, ticket, resumed_at=msk(2026, 7, 27, 9, 0))  # Monday opening
    db.refresh(ticket)
    assert ticket.sla_paused_working_minutes_total == 0
    assert ticket.sla_resolution_due_at == msk(2026, 7, 21, 14, 0)


def test_resolution_met_fixed_on_first_resolve_and_kept_on_reopen(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact, anchored=False)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    db.refresh(ticket)
    assert ticket.sla_resolution_met is True
    first_resolved_at = ticket.resolved_at

    # Client replies -> reopen; the recorded outcome must survive.
    messages_service.add_message(db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Не работает"))
    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.IN_PROGRESS
    assert ticket.resolved_at == first_resolved_at
    assert ticket.sla_resolution_met is True


def test_late_resolution_marks_violation(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact)  # resolution due 14:00 MSK 2026-07-21 (in the past)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    db.refresh(ticket)
    assert ticket.sla_resolution_met is False


def test_priority_change_recomputes_running_deadlines(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact)
    tickets_service.update_ticket(
        db,
        ticket,
        TicketUpdate(manual_priority=Priority.P3, manual_priority_reason="Есть обходное решение"),
        actor=None,
    )
    db.refresh(ticket)
    # P3 = 240/1440 working minutes from Tuesday 10:00: reaction Tuesday 14:00,
    # resolution 24 working hours -> Friday 2026-07-24 16:00 (8h Tue + 9h Wed + 9h Thu ... clipped windows:
    # Tue 10:00-18:00 = 8h, Wed 9h, Thu 9h -> 26h > 24h; 24h lands Thu 17:00? 8+9=17h by Wed close, +7h Thu -> 16:00)
    assert ticket.sla_reaction_due_at == msk(2026, 7, 21, 14, 0)
    assert ticket.sla_resolution_due_at == msk(2026, 7, 23, 16, 0)
    assert ticket.sla_reaction_warned_at is None
    assert ticket.sla_resolution_warned_at is None


# --- escalations -------------------------------------------------------------


def _assign(db: Session, ticket: Ticket, engineer: User, lead: User | None = None) -> None:
    if lead is not None:
        team = Team(name="Тестовая группа", lead_user_id=lead.id)
        db.add(team)
        db.flush()
        ticket.team_id = team.id
    ticket.assigned_engineer_id = engineer.id
    db.commit()


def _notifications(db: Session, ticket: Ticket) -> list[Notification]:
    return db.query(Notification).filter(Notification.ticket_id == ticket.id).order_by(Notification.id).all()


def test_escalation_warns_assignee_at_75_percent(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact)
    _assign(db, ticket, engineer_user)
    # 23 of 30 reaction minutes consumed (76%) - warning, no breach.
    touched = sla.run_escalations(db, now=msk(2026, 7, 21, 10, 23))
    db.refresh(ticket)
    assert touched == 1
    assert ticket.sla_reaction_warned_at is not None
    assert ticket.sla_reaction_met is None
    notes = _notifications(db, ticket)
    assert [n.type for n in notes] == [NotificationType.SLA_REACTION_WARNING]
    assert notes[0].user_id == engineer_user.id


def test_escalation_fixes_breach_and_notifies_team_lead(db: Session, contact: Contact, engineer_user: User):
    lead = User(full_name="Руководитель", email="lead.test@o-horizons.com", password_hash="x", role="manager")
    db.add(lead)
    db.flush()
    ticket = _make_ticket(db, contact)
    _assign(db, ticket, engineer_user, lead=lead)

    touched = sla.run_escalations(db, now=msk(2026, 7, 21, 10, 31))
    db.refresh(ticket)
    assert touched == 1
    assert ticket.sla_reaction_met is False
    assert ticket.sla_reaction_escalated_at is not None
    recipients = {n.user_id for n in _notifications(db, ticket) if n.type == NotificationType.SLA_REACTION_BREACH}
    assert recipients == {engineer_user.id, lead.id}


def test_escalation_fires_exactly_once(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact)
    _assign(db, ticket, engineer_user)
    now = msk(2026, 7, 21, 10, 31)
    assert sla.run_escalations(db, now=now) == 1
    count_after_first = len(_notifications(db, ticket))
    assert sla.run_escalations(db, now=now + timedelta(minutes=5)) == 0
    assert len(_notifications(db, ticket)) == count_after_first


def test_resolution_escalation_skipped_while_paused(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact)
    _assign(db, ticket, engineer_user)
    ticket.first_response_at = msk(2026, 7, 21, 10, 5)  # reaction timer finished
    ticket.sla_reaction_met = True
    ticket.status = TicketStatus.WAITING_CUSTOMER
    ticket.sla_paused_at = msk(2026, 7, 21, 11, 0)
    db.commit()

    # Way past the 14:00 resolution due, but the ticket is on hold - no escalation.
    assert sla.run_escalations(db, now=msk(2026, 7, 21, 15, 0)) == 0
    db.refresh(ticket)
    assert ticket.sla_resolution_met is None
    assert ticket.sla_resolution_escalated_at is None


def test_resolution_breach_escalates_after_due(db: Session, contact: Contact, engineer_user: User):
    ticket = _make_ticket(db, contact)
    _assign(db, ticket, engineer_user)
    ticket.first_response_at = msk(2026, 7, 21, 10, 5)
    ticket.sla_reaction_met = True
    db.commit()

    assert sla.run_escalations(db, now=msk(2026, 7, 21, 14, 1)) == 1
    db.refresh(ticket)
    assert ticket.sla_resolution_met is False
    types = [n.type for n in _notifications(db, ticket)]
    assert NotificationType.SLA_RESOLUTION_BREACH in types


# --- API view ----------------------------------------------------------------


def test_compute_view_states(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact)
    view = sla.compute_view(db, ticket, now=msk(2026, 7, 21, 10, 10))
    assert view["reaction"]["state"] == "ok"
    assert view["resolution"]["state"] == "ok"

    view = sla.compute_view(db, ticket, now=msk(2026, 7, 21, 10, 25))
    assert view["reaction"]["state"] == "warning"

    view = sla.compute_view(db, ticket, now=msk(2026, 7, 21, 11, 0))
    assert view["reaction"]["state"] == "breached"

    ticket.sla_paused_at = msk(2026, 7, 21, 11, 0)
    ticket.status = TicketStatus.WAITING_CUSTOMER
    view = sla.compute_view(db, ticket, now=msk(2026, 7, 21, 12, 0))
    assert view["resolution"]["state"] == "paused"
    assert view["paused"] is True


def test_compute_view_no_deadline_hides_progress(db: Session, contact: Contact):
    # Ticket predating the Stage 3 engine (e.g. created under Stage 1/2): a
    # rule exists for its tariff/priority but due_at was never computed. The
    # view must say "no_rule" without a nonsensical elapsed-time percentage.
    ticket = _make_ticket(db, contact, anchored=False)
    ticket.sla_reaction_due_at = None
    ticket.sla_resolution_due_at = None
    view = sla.compute_view(db, ticket, now=msk(2026, 7, 21, 10, 5))
    assert view["reaction"] == {"due_at": None, "met": None, "state": "no_rule", "progress_pct": None}
    assert view["resolution"] == {"due_at": None, "met": None, "state": "no_rule", "progress_pct": None}


def test_backfill_sets_deadlines_for_pre_engine_tickets(db: Session, contact: Contact):
    ticket = _make_ticket(db, contact, anchored=False)
    ticket.created_at = ANCHOR
    ticket.sla_reaction_due_at = None
    ticket.sla_resolution_due_at = None
    db.commit()

    touched = sla.backfill_missing_deadlines(db)
    db.refresh(ticket)
    assert touched == 1
    assert ticket.sla_reaction_due_at == msk(2026, 7, 21, 10, 30)
    assert ticket.sla_resolution_due_at == msk(2026, 7, 21, 14, 0)


def test_backfill_skips_tickets_already_in_progress(db: Session, contact: Contact, engineer_user: User):
    # A ticket that already received a reply or resolution before the engine
    # existed shouldn't be judged retroactively - leave it as "no_rule" rather
    # than fabricate a pass/fail against a deadline that was never in force.
    ticket = _make_ticket(db, contact, anchored=False)
    ticket.sla_reaction_due_at = None
    ticket.sla_resolution_due_at = None
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Ответ до движка"), author_user=engineer_user
    )
    db.refresh(ticket)
    assert ticket.sla_reaction_due_at is None  # add_message no longer back-derives a deadline

    touched = sla.backfill_missing_deadlines(db)
    db.refresh(ticket)
    assert touched == 0
    assert ticket.sla_reaction_due_at is None
    assert ticket.sla_reaction_met is None
