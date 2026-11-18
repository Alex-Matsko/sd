"""Explicit result/history fixtures for tests unrelated to the acceptance flow.

The real publish/accept workflow is covered by test_customer_acceptance and
test_audit_regressions. Legacy closed rows must remain readable too.
"""
from datetime import datetime, timezone
from app.core.enums import MessageDirection, TicketStatus
from app.models.message import Message


def accepted_result(db, ticket):
    message = Message(ticket_id=ticket.id, channel=ticket.channel,
                      direction=MessageDirection.OUTBOUND, body='Результат тестовой работы')
    db.add(message); db.flush()
    ticket.resolution_message_id = message.id
    ticket.accepted_at = datetime.now(timezone.utc)
    db.flush()


def legacy_closed(db, ticket):
    ticket.status = TicketStatus.CLOSED
    ticket.closed_at = datetime.now(timezone.utc)
    db.commit()
