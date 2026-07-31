"""Automation rule engine tests (section 4.2 auto-close). The seeded default
rule (RESOLVED_WITHOUT_REPLY, 3 days) is used directly rather than creating a
fresh one per test, matching how test_sla.py reuses the seeded default tariff."""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.enums import AutomationTriggerType, TicketStatus, TicketType, MessageDirection, Priority, Channel
from app.models.audit import AuditLog
from app.models.automation_rule import AutomationRule
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import automation, messages as messages_service
from app.services import tickets as tickets_service


def _default_rule(db: Session) -> AutomationRule:
    rule = (
        db.query(AutomationRule)
        .filter(AutomationRule.trigger_type == AutomationTriggerType.RESOLVED_WITHOUT_REPLY)
        .first()
    )
    assert rule is not None, "run `python -m app.seed` against the test database before running tests"
    return rule


def _make_ticket(db: Session, contact: Contact) -> Ticket:
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.PORTAL,
        subject="Тестовая заявка",
        manual_priority=Priority.P3,
        manual_priority_reason="test",
    )
    return tickets_service.create_ticket(db, payload, actor=None)


def _resolve_days_ago(db: Session, ticket: Ticket, days: float) -> None:
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    # Shift the *whole* status-change trail back by the same amount, not just
    # the last entry - backdating only the newest row would leave it with an
    # earlier timestamp than the IN_PROGRESS row before it, inverting the
    # audit order that _time_in_current_status relies on to find "most recent".
    shift = timedelta(days=days)
    changes = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket.id, AuditLog.action == "status_changed")
        .all()
    )
    for change in changes:
        change.created_at = change.created_at - shift
        db.add(change)
    db.commit()


def test_auto_close_fires_after_threshold(db: Session, contact: Contact):
    rule = _default_rule(db)
    ticket = _make_ticket(db, contact)
    _resolve_days_ago(db, ticket, rule.threshold_days + 1)

    touched = automation.run_automation_rules(db)
    db.refresh(ticket)

    assert touched == 1
    assert TicketStatus(ticket.status) == TicketStatus.CLOSED
    assert ticket.closed_at is not None


def test_auto_close_does_not_fire_before_threshold(db: Session, contact: Contact):
    rule = _default_rule(db)
    ticket = _make_ticket(db, contact)
    _resolve_days_ago(db, ticket, max(rule.threshold_days - 1, 0.1))

    touched = automation.run_automation_rules(db)
    db.refresh(ticket)

    assert touched == 0
    assert TicketStatus(ticket.status) == TicketStatus.RESOLVED


def test_inactive_rule_does_not_fire(db: Session, contact: Contact):
    rule = _default_rule(db)
    rule.is_active = False
    db.add(rule)
    db.commit()

    ticket = _make_ticket(db, contact)
    _resolve_days_ago(db, ticket, rule.threshold_days + 5)

    touched = automation.run_automation_rules(db)
    db.refresh(ticket)

    assert touched == 0
    assert TicketStatus(ticket.status) == TicketStatus.RESOLVED


def test_custom_threshold_is_respected(db: Session, contact: Contact):
    rule = _default_rule(db)
    rule.threshold_days = 1
    db.add(rule)
    db.commit()

    ticket = _make_ticket(db, contact)
    _resolve_days_ago(db, ticket, 1.5)

    touched = automation.run_automation_rules(db)
    db.refresh(ticket)

    assert touched == 1
    assert TicketStatus(ticket.status) == TicketStatus.CLOSED


def test_client_reply_removes_ticket_from_auto_close_candidates(db: Session, contact: Contact):
    rule = _default_rule(db)
    ticket = _make_ticket(db, contact)
    _resolve_days_ago(db, ticket, rule.threshold_days + 5)

    # Client replies - the existing reopen rule (services/messages.add_message)
    # already flips it out of RESOLVED before the automation sweep ever runs.
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Проблема осталась"), author_contact=contact
    )
    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.IN_PROGRESS

    touched = automation.run_automation_rules(db)
    db.refresh(ticket)

    assert touched == 0
    assert TicketStatus(ticket.status) == TicketStatus.IN_PROGRESS


def test_reresolved_ticket_uses_latest_resolution_time_not_first(db: Session, contact: Contact):
    """resolved_at is fixed at the *first* resolution forever (docs/decisions.md);
    the automation candidate window must track the *current* time-in-status via
    the audit trail, or a ticket resolved long ago, reopened, and just
    re-resolved would be incorrectly auto-closed immediately."""
    rule = _default_rule(db)
    ticket = _make_ticket(db, contact)
    _resolve_days_ago(db, ticket, rule.threshold_days + 10)  # first resolution, long ago

    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Снова сломалось"), author_contact=contact
    )
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)  # just re-resolved, now
    db.refresh(ticket)

    touched = automation.run_automation_rules(db)
    db.refresh(ticket)

    assert touched == 0
    assert TicketStatus(ticket.status) == TicketStatus.RESOLVED
