"""SLA engine (Stage 3, section 4.3).

Deadlines are working-time offsets from the ticket's creation moment, computed
over the tariff's business calendar. Pauses ("Ожидает клиента"/"Ожидает третью
сторону") accumulate into `sla_paused_working_minutes_total`, so at any point:

    resolution_due = created_at +working (resolution_minutes + paused_working_total)

which makes pause shifts and priority-change recomputes the same operation.
Reaction/resolution outcomes (`sla_*_met`) are fixed once - at first response,
at first resolve, or by the escalation scan at breach - and never recomputed
afterwards (docs/decisions.md: reopening keeps the original result).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import NotificationType, SLA_PAUSING_STATUSES, SlaTimerState, TicketStatus
from app.models.notification import Notification
from app.models.tariff import Tariff, TariffSlaRule
from app.models.team import Team
from app.models.ticket import Ticket
from app.services import audit
from app.services.calendar_math import (
    CalendarSpec,
    add_working_minutes,
    load_spec,
    working_minutes_between,
)


@dataclass
class SlaCache:
    """Per-request/per-scan cache: calendars and SLA rules are tiny reference
    tables read for every ticket in a list."""

    specs: dict[int, CalendarSpec] = field(default_factory=dict)
    tariff_calendar: dict[int, int] = field(default_factory=dict)
    rules: dict[tuple[int, str], TariffSlaRule | None] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rule_for(db: Session, ticket: Ticket, cache: SlaCache) -> TariffSlaRule | None:
    key = (ticket.tariff_id, str(ticket.priority))
    if key not in cache.rules:
        cache.rules[key] = (
            db.query(TariffSlaRule)
            .filter(TariffSlaRule.tariff_id == ticket.tariff_id, TariffSlaRule.priority == ticket.priority)
            .first()
        )
    return cache.rules[key]


def _spec_for(db: Session, ticket: Ticket, cache: SlaCache) -> CalendarSpec:
    if ticket.tariff_id not in cache.tariff_calendar:
        tariff = db.get(Tariff, ticket.tariff_id)
        cache.tariff_calendar[ticket.tariff_id] = tariff.business_calendar_id
    calendar_id = cache.tariff_calendar[ticket.tariff_id]
    if calendar_id not in cache.specs:
        cache.specs[calendar_id] = load_spec(db, calendar_id)
    return cache.specs[calendar_id]


def _anchor(ticket: Ticket) -> datetime:
    return ticket.created_at if ticket.created_at is not None else _now()


def _refresh_resolution_due(db: Session, ticket: Ticket, cache: SlaCache) -> None:
    rule = _rule_for(db, ticket, cache)
    if rule is None:
        ticket.sla_resolution_due_at = None
        return
    spec = _spec_for(db, ticket, cache)
    ticket.sla_resolution_due_at = add_working_minutes(
        spec, _anchor(ticket), rule.resolution_time_minutes + (ticket.sla_paused_working_minutes_total or 0)
    )


def set_initial_deadlines(db: Session, ticket: Ticket, cache: SlaCache | None = None) -> None:
    """Called once at ticket creation, after flush (created_at available)."""
    cache = cache or SlaCache()
    rule = _rule_for(db, ticket, cache)
    if rule is None:
        return
    spec = _spec_for(db, ticket, cache)
    ticket.sla_reaction_due_at = add_working_minutes(spec, _anchor(ticket), rule.reaction_time_minutes)
    ticket.sla_resolution_due_at = add_working_minutes(spec, _anchor(ticket), rule.resolution_time_minutes)


def apply_resume(db: Session, ticket: Ticket, resumed_at: datetime, cache: SlaCache | None = None) -> None:
    """Resuming from a pausing status: fold the pause into the accumulated
    working-minute total and push the resolution deadline out accordingly."""
    if ticket.sla_paused_at is None:
        return
    cache = cache or SlaCache()
    spec = _spec_for(db, ticket, cache)
    ticket.sla_paused_working_minutes_total = (ticket.sla_paused_working_minutes_total or 0) + working_minutes_between(
        spec, ticket.sla_paused_at, resumed_at
    )
    if ticket.resolved_at is None and ticket.sla_resolution_met is None:
        _refresh_resolution_due(db, ticket, cache)


def register_first_response(ticket: Ticket, now: datetime | None = None) -> None:
    if ticket.first_response_at is not None:
        return
    now = now or _now()
    ticket.first_response_at = now
    # A breach already fixed by the escalation scan stays fixed.
    if ticket.sla_reaction_due_at is not None and ticket.sla_reaction_met is None:
        ticket.sla_reaction_met = now <= ticket.sla_reaction_due_at


def register_resolution(ticket: Ticket, now: datetime | None = None) -> None:
    if ticket.sla_resolution_due_at is not None and ticket.sla_resolution_met is None:
        ticket.sla_resolution_met = (now or _now()) <= ticket.sla_resolution_due_at


def recompute_after_priority_change(db: Session, ticket: Ticket, cache: SlaCache | None = None) -> None:
    """Priority change re-targets still-running timers to the new rule's budget.
    Escalation stamps reset so 75%/100% notifications fire against the new
    deadline; an already-passed breach un-fixes only if the new deadline is in
    the future. Finished timers (response given / first resolve) keep their
    recorded outcome."""
    cache = cache or SlaCache()
    now = _now()
    rule = _rule_for(db, ticket, cache)

    if ticket.first_response_at is None:
        if rule is None:
            ticket.sla_reaction_due_at = None
        else:
            spec = _spec_for(db, ticket, cache)
            ticket.sla_reaction_due_at = add_working_minutes(spec, _anchor(ticket), rule.reaction_time_minutes)
        ticket.sla_reaction_warned_at = None
        ticket.sla_reaction_escalated_at = None
        if ticket.sla_reaction_met is False and (
            ticket.sla_reaction_due_at is None or now < ticket.sla_reaction_due_at
        ):
            ticket.sla_reaction_met = None

    if ticket.resolved_at is None:
        _refresh_resolution_due(db, ticket, cache)
        ticket.sla_resolution_warned_at = None
        ticket.sla_resolution_escalated_at = None
        if ticket.sla_resolution_met is False and (
            ticket.sla_resolution_due_at is None or now < ticket.sla_resolution_due_at
        ):
            ticket.sla_resolution_met = None


def _timer_view(
    due_at: datetime | None,
    met: bool | None,
    consumed_minutes: int | None,
    total_minutes: int | None,
    now: datetime,
    paused: bool,
) -> dict:
    progress = None
    if due_at is not None and total_minutes and consumed_minutes is not None:
        progress = min(round(consumed_minutes / total_minutes * 100), 999)
    if due_at is None or total_minutes is None:
        state = SlaTimerState.NO_RULE
    elif met is True:
        state = SlaTimerState.MET
    elif met is False:
        state = SlaTimerState.BREACHED
    elif paused:
        state = SlaTimerState.PAUSED
    elif now >= due_at:
        state = SlaTimerState.BREACHED
    elif progress is not None and progress >= settings.sla_warning_threshold * 100:
        state = SlaTimerState.WARNING
    else:
        state = SlaTimerState.OK
    return {"due_at": due_at, "met": met, "state": state, "progress_pct": progress}


def compute_view(db: Session, ticket: Ticket, cache: SlaCache | None = None, now: datetime | None = None) -> dict:
    """SLA block for API serialization: state + progress for both timers."""
    cache = cache or SlaCache()
    now = now or _now()
    rule = _rule_for(db, ticket, cache)
    anchor = _anchor(ticket)
    paused = ticket.sla_paused_at is not None
    paused_total = ticket.sla_paused_working_minutes_total or 0

    reaction_consumed = resolution_consumed = None
    if rule is not None:
        spec = _spec_for(db, ticket, cache)
        reaction_end = ticket.first_response_at or now
        reaction_consumed = working_minutes_between(spec, anchor, reaction_end)
        resolution_end = ticket.resolved_at or (ticket.sla_paused_at if paused else now)
        resolution_consumed = max(working_minutes_between(spec, anchor, resolution_end) - paused_total, 0)

    return {
        "reaction": _timer_view(
            ticket.sla_reaction_due_at,
            ticket.sla_reaction_met,
            reaction_consumed,
            rule.reaction_time_minutes if rule else None,
            now,
            paused=False,  # reaction timer never pauses (section 4.2 pauses the resolution timer)
        ),
        "resolution": _timer_view(
            ticket.sla_resolution_due_at,
            ticket.sla_resolution_met,
            resolution_consumed,
            rule.resolution_time_minutes if rule else None,
            now,
            paused=paused and ticket.resolved_at is None and ticket.sla_resolution_met is None,
        ),
        "paused": paused,
    }


def _notify(db: Session, user_ids: set[int], type_: NotificationType, ticket: Ticket, title: str) -> None:
    for user_id in user_ids:
        db.add(Notification(user_id=user_id, ticket_id=ticket.id, type=type_, title=title))


def _warning_recipients(db: Session, ticket: Ticket) -> set[int]:
    if ticket.assigned_engineer_id:
        return {ticket.assigned_engineer_id}
    return _team_lead(db, ticket)


def _breach_recipients(db: Session, ticket: Ticket) -> set[int]:
    recipients = _team_lead(db, ticket)
    if ticket.assigned_engineer_id:
        recipients.add(ticket.assigned_engineer_id)
    return recipients


def _team_lead(db: Session, ticket: Ticket) -> set[int]:
    if ticket.team_id:
        team = db.get(Team, ticket.team_id)
        if team is not None and team.lead_user_id:
            return {team.lead_user_id}
    return set()


def backfill_missing_deadlines(db: Session) -> int:
    """One-time-per-ticket backfill for rows that predate this engine (see
    models/ticket.py: the SLA columns shipped nullable in Stage 1 so Stage 3
    wouldn't need a schema migration). Only touches tickets that never
    progressed - no reply, no resolution - so nothing here fabricates a
    pass/fail judgment against a deadline that wasn't in force at the time.
    Idempotent: once due_at is set, the ticket no longer matches. Called from
    app.seed on every container start, like the rest of the bootstrap data."""
    cache = SlaCache()
    candidates = (
        db.query(Ticket)
        .filter(
            Ticket.sla_reaction_due_at.is_(None),
            Ticket.first_response_at.is_(None),
            Ticket.resolved_at.is_(None),
            Ticket.status.notin_([TicketStatus.CLOSED, TicketStatus.CANCELLED]),
        )
        .all()
    )
    for ticket in candidates:
        set_initial_deadlines(db, ticket, cache)
        db.add(ticket)
    if candidates:
        db.commit()
    return len(candidates)


def run_escalations(db: Session, now: datetime | None = None) -> int:
    """One escalation sweep (worker calls this every minute): 75% -> warn the
    assignee, 100% -> fix the breach and escalate to the team lead. Stamps on
    the ticket make every notification fire exactly once. Returns the number of
    tickets updated; commits when anything changed."""
    now = now or _now()
    cache = SlaCache()
    threshold = settings.sla_warning_threshold

    reaction_pending = and_(
        Ticket.first_response_at.is_(None),
        Ticket.sla_reaction_met.is_(None),
        Ticket.sla_reaction_due_at.isnot(None),
    )
    resolution_pending = and_(
        Ticket.resolved_at.is_(None),
        Ticket.sla_resolution_met.is_(None),
        Ticket.sla_resolution_due_at.isnot(None),
    )
    candidates = (
        db.query(Ticket)
        .filter(
            Ticket.status.notin_([TicketStatus.CLOSED, TicketStatus.CANCELLED]),
            or_(reaction_pending, resolution_pending),
        )
        .all()
    )

    touched = 0
    for ticket in candidates:
        rule = _rule_for(db, ticket, cache)
        if rule is None:
            continue
        spec = _spec_for(db, ticket, cache)
        anchor = _anchor(ticket)
        changed = False

        if ticket.first_response_at is None and ticket.sla_reaction_met is None and ticket.sla_reaction_due_at:
            if now >= ticket.sla_reaction_due_at:
                ticket.sla_reaction_met = False
                ticket.sla_reaction_escalated_at = now
                _notify(
                    db,
                    _breach_recipients(db, ticket),
                    NotificationType.SLA_REACTION_BREACH,
                    ticket,
                    f"SLA нарушен: нет реакции по {ticket.display_number} в срок",
                )
                audit.record(
                    db,
                    entity_type="ticket",
                    entity_id=ticket.id,
                    action="sla_reaction_breached",
                    user_id=None,
                    changes={"due_at": ticket.sla_reaction_due_at.isoformat()},
                )
                changed = True
            elif ticket.sla_reaction_warned_at is None:
                consumed = working_minutes_between(spec, anchor, now)
                if consumed >= rule.reaction_time_minutes * threshold:
                    ticket.sla_reaction_warned_at = now
                    _notify(
                        db,
                        _warning_recipients(db, ticket),
                        NotificationType.SLA_REACTION_WARNING,
                        ticket,
                        f"SLA: по {ticket.display_number} израсходовано 75% времени реакции",
                    )
                    changed = True

        resolution_running = (
            ticket.resolved_at is None
            and ticket.sla_resolution_met is None
            and ticket.sla_resolution_due_at is not None
            and TicketStatus(ticket.status) not in SLA_PAUSING_STATUSES
        )
        if resolution_running:
            if now >= ticket.sla_resolution_due_at:
                ticket.sla_resolution_met = False
                ticket.sla_resolution_escalated_at = now
                _notify(
                    db,
                    _breach_recipients(db, ticket),
                    NotificationType.SLA_RESOLUTION_BREACH,
                    ticket,
                    f"SLA нарушен: {ticket.display_number} не решена в срок",
                )
                audit.record(
                    db,
                    entity_type="ticket",
                    entity_id=ticket.id,
                    action="sla_resolution_breached",
                    user_id=None,
                    changes={"due_at": ticket.sla_resolution_due_at.isoformat()},
                )
                changed = True
            elif ticket.sla_resolution_warned_at is None:
                consumed = working_minutes_between(spec, anchor, now) - (ticket.sla_paused_working_minutes_total or 0)
                if consumed >= rule.resolution_time_minutes * threshold:
                    ticket.sla_resolution_warned_at = now
                    _notify(
                        db,
                        _warning_recipients(db, ticket),
                        NotificationType.SLA_RESOLUTION_WARNING,
                        ticket,
                        f"SLA: по {ticket.display_number} израсходовано 75% времени решения",
                    )
                    changed = True

        if changed:
            db.add(ticket)
            touched += 1

    if touched:
        db.commit()
    return touched
