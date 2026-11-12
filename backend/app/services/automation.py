"""Status-automation rule engine (section 4.2: "«Решена» → «Закрыта»:
автозакрытие через N дней без ответа клиента"). Evaluated by the worker on
the same cadence as the SLA sweep - see app/worker.py.

Supports time in status and time without a customer reply.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.enums import AutomationTriggerType, MessageDirection
from app.models.audit import AuditLog
from app.models.automation_rule import AutomationRule
from app.models.ticket import Ticket
from app.models.message import Message
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


def _run_rule(db: Session, rule: AutomationRule, now: datetime, handled: set[int]) -> int:
    candidate_ids = [row[0] for row in db.query(Ticket.id).filter(Ticket.status == rule.from_status).order_by(Ticket.id)]
    touched = 0
    for ticket_id in candidate_ids:
        if ticket_id in handled:
            continue
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.status == rule.from_status).with_for_update(skip_locked=True).first()
        if ticket is None:
            continue
        since = _time_in_current_status(db, ticket)
        if rule.trigger_type in (AutomationTriggerType.RESOLVED_WITHOUT_REPLY, AutomationTriggerType.STATUS_WITHOUT_REPLY):
            last_reply = db.query(func.max(Message.created_at)).filter(Message.ticket_id == ticket.id,
                Message.direction == MessageDirection.INBOUND).scalar()
            if last_reply is not None:
                since = max(since, last_reply)
        if now - since >= timedelta(days=rule.threshold_days):
            # The status service commits this audit alongside the transition.
            db.add(AuditLog(entity_type="ticket", entity_id=ticket.id, action="automation_applied",
                            user_id=None, changes={"rule_id": rule.id, "rule_name": rule.name}))
            tickets_service.transition_status(db, ticket, rule.to_status, actor=None)
            handled.add(ticket.id)
            touched += 1
    return touched


def run_automation_rules(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    rules = db.query(AutomationRule).filter(AutomationRule.is_active.is_(True)).order_by(AutomationRule.id).all()
    touched = 0
    handled: set[int] = set()
    for rule in rules:
        if rule.threshold_days < 1 or rule.to_status not in tickets_service.ALLOWED_TRANSITIONS.get(rule.from_status, set()):
            continue
        touched += _run_rule(db, rule, now, handled)
    return touched
