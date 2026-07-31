"""Status-automation rule engine (section 4.2: "«Решена» → «Закрыта»:
автозакрытие через N дней без ответа клиента"). Evaluated by the worker on
the same cadence as the SLA sweep - see app/worker.py.

Only one trigger type exists today (RESOLVED_WITHOUT_REPLY); see
models/automation_rule.py for why this isn't a generic rule DSL.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.enums import AutomationTriggerType
from app.models.audit import AuditLog
from app.models.automation_rule import AutomationRule
from app.models.ticket import Ticket
from app.services import tickets as tickets_service


def _time_in_current_status(db: Session, ticket: Ticket) -> datetime:
    """When the ticket most recently transitioned into its current status.
    Falls back to created_at for tickets that have never had a recorded
    transition (e.g. created directly into a routed status)."""
    # id as a tiebreaker: Postgres now() is transaction-start time, so two
    # transitions made in the same transaction can share created_at exactly
    # (see services/email_channel.py for the same fix).
    last_change = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket.id, AuditLog.action == "status_changed")
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .first()
    )
    return last_change.created_at if last_change is not None else ticket.created_at


def _run_resolved_without_reply(db: Session, rule: AutomationRule, now: datetime) -> int:
    # A client reply while RESOLVED already flips the ticket back to
    # IN_PROGRESS (services/messages.add_message) before this ever runs, so
    # "still RESOLVED" already means "no reply since" - no extra check needed.
    candidates = db.query(Ticket).filter(Ticket.status == rule.from_status).all()
    touched = 0
    for ticket in candidates:
        resolved_since = _time_in_current_status(db, ticket)
        if now - resolved_since >= timedelta(days=rule.threshold_days):
            tickets_service.transition_status(db, ticket, rule.to_status, actor=None)
            touched += 1
    return touched


def run_automation_rules(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    rules = db.query(AutomationRule).filter(AutomationRule.is_active.is_(True)).all()
    touched = 0
    for rule in rules:
        if rule.trigger_type == AutomationTriggerType.RESOLVED_WITHOUT_REPLY:
            touched += _run_resolved_without_reply(db, rule, now)
    return touched
