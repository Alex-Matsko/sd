from datetime import datetime, timedelta, timezone

import pytest

from app.core.enums import (
    Channel,
    ImpactUrgencyLevel,
    MessageDirection,
    Priority,
    RoutingRuleType,
    TicketStatus,
    TicketType,
)
from app.models.routing import RoutingRule
from app.schemas.message import MessageCreate
from app.schemas.ticket import TicketCreate
from app.services import messages as messages_service
from app.services import tickets as tickets_service


def _minimal_ticket(db, contact, **overrides):
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.TELEGRAM,
        subject="Тестовая заявка",
        manual_priority=Priority.P3,
        manual_priority_reason="фикстура теста",
        **overrides,
    )
    return tickets_service.create_ticket(db, payload, actor=None)


def test_create_ticket_resolves_contract_tariff_and_matrix_priority(db, contact, active_contract):
    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.TELEGRAM,
        subject="Не работает 1С",
        impact=ImpactUrgencyLevel.HIGH,
        urgency=ImpactUrgencyLevel.HIGH,
    )
    ticket = tickets_service.create_ticket(db, payload, actor=None)

    assert ticket.organization_id == contact.organization_id
    assert ticket.contract_id == active_contract.id
    assert ticket.has_no_active_contract is False
    assert ticket.priority == Priority.P1
    assert ticket.display_number == f"OH-{ticket.number}"


def test_create_ticket_without_contract_falls_back_and_flags(db, contact, default_tariff):
    ticket = _minimal_ticket(db, contact)
    assert ticket.contract_id is None
    assert ticket.has_no_active_contract is True
    assert ticket.tariff_id == default_tariff.id


def test_create_ticket_requires_priority_source():
    with pytest.raises(ValueError):
        TicketCreate(contact_id=1, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject="x")


def test_create_ticket_applies_routing_rule_and_moves_to_assigned(db, contact, organization, engineer_user):
    db.add(
        RoutingRule(
            order=1,
            rule_type=RoutingRuleType.ORGANIZATION_TO_ENGINEER,
            organization_id=organization.id,
            target_engineer_id=engineer_user.id,
        )
    )
    db.commit()

    ticket = _minimal_ticket(db, contact)
    assert ticket.assigned_engineer_id == engineer_user.id
    assert ticket.status == TicketStatus.ASSIGNED


def test_create_ticket_without_routing_match_stays_new(db, contact):
    ticket = _minimal_ticket(db, contact)
    assert ticket.status == TicketStatus.NEW
    assert ticket.assigned_engineer_id is None


def test_invalid_status_transition_raises(db, contact):
    ticket = _minimal_ticket(db, contact)
    with pytest.raises(ValueError):
        tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)


def test_waiting_customer_pause_accumulates_elapsed_minutes(db, contact):
    ticket = _minimal_ticket(db, contact)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.WAITING_CUSTOMER, actor=None)
    assert ticket.sla_paused_at is not None

    ticket.sla_paused_at = datetime.now(timezone.utc) - timedelta(minutes=15)
    db.add(ticket)
    db.commit()

    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    assert ticket.sla_paused_at is None
    assert ticket.sla_paused_minutes_total >= 15


def test_client_reply_returns_waiting_customer_ticket_to_in_progress(db, contact):
    ticket = _minimal_ticket(db, contact)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.WAITING_CUSTOMER, actor=None)

    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Вот доп. информация"), author_contact=contact
    )
    db.refresh(ticket)
    assert ticket.status == TicketStatus.IN_PROGRESS


def test_reopen_via_client_reply_keeps_original_resolution_fixed(db, contact):
    """docs/decisions.md: "SLA при переоткрытии заявки клиентом" - the first
    resolution timestamp/result must never be overwritten by a later reopen."""
    ticket = _minimal_ticket(db, contact)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    first_resolved_at = ticket.resolved_at
    assert first_resolved_at is not None

    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Проблема повторилась"), author_contact=contact
    )
    db.refresh(ticket)

    assert ticket.status == TicketStatus.IN_PROGRESS
    assert ticket.resolved_at == first_resolved_at

    # Resolving a second time must not move resolved_at either.
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    assert ticket.resolved_at == first_resolved_at


def test_first_outbound_message_sets_first_response_at(db, contact, engineer_user):
    ticket = _minimal_ticket(db, contact)
    assert ticket.first_response_at is None

    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.OUTBOUND, body="Принято в работу"), author_user=engineer_user
    )
    db.refresh(ticket)
    assert ticket.first_response_at is not None


def test_manual_priority_override_requires_reason(db, contact):
    ticket = _minimal_ticket(db, contact)
    from app.schemas.ticket import TicketUpdate

    with pytest.raises(ValueError):
        tickets_service.update_ticket(db, ticket, TicketUpdate(manual_priority=Priority.P1), actor=None)
