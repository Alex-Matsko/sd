from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import ImpactUrgencyLevel, SLA_PAUSING_STATUSES, TicketStatus
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import audit, priority as priority_service, routing
from app.services.contracts import resolve_contract_and_tariff

# Allowed status transitions (section 4.2). CLOSED and CANCELLED are terminal.
ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.NEW: {TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.ASSIGNED: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.IN_PROGRESS: {
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.WAITING_THIRD_PARTY,
        TicketStatus.RESOLVED,
        TicketStatus.CANCELLED,
    },
    TicketStatus.WAITING_CUSTOMER: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.WAITING_THIRD_PARTY: {TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.RESOLVED: {TicketStatus.CLOSED, TicketStatus.IN_PROGRESS},
    TicketStatus.CLOSED: set(),
    TicketStatus.CANCELLED: set(),
}


def create_ticket(db: Session, payload: TicketCreate, actor: User | None) -> Ticket:
    contact = db.get(Contact, payload.contact_id)
    if contact is None:
        raise ValueError("Контакт не найден")

    contract, tariff, has_no_active_contract = resolve_contract_and_tariff(db, contact.organization_id)

    if payload.manual_priority is not None:
        ticket_priority = payload.manual_priority
    else:
        ticket_priority = priority_service.compute_priority(db, payload.impact, payload.urgency)

    team_id, engineer_id = routing.resolve_assignment(db, contact.organization_id, payload.category_id)
    status = TicketStatus.ASSIGNED if (team_id or engineer_id) else TicketStatus.NEW

    ticket = Ticket(
        type=payload.type,
        channel=payload.channel,
        subject=payload.subject,
        organization_id=contact.organization_id,
        contact_id=contact.id,
        contract_id=contract.id if contract else None,
        tariff_id=tariff.id,
        has_no_active_contract=has_no_active_contract,
        asset_id=payload.asset_id,
        category_id=payload.category_id,
        impact=payload.impact,
        urgency=payload.urgency,
        priority=ticket_priority,
        priority_override_reason=payload.manual_priority_reason,
        status=status,
        assigned_engineer_id=engineer_id,
        team_id=team_id,
    )
    db.add(ticket)
    db.flush()

    if payload.initial_message:
        from app.core.enums import MessageDirection
        from app.schemas.message import MessageCreate
        from app.services import messages as messages_service

        messages_service.add_message(
            db,
            ticket,
            MessageCreate(direction=MessageDirection.INBOUND, body=payload.initial_message, channel=payload.channel),
            author_contact=contact,
        )

    audit.record(
        db,
        entity_type="ticket",
        entity_id=ticket.id,
        action="created",
        user_id=actor.id if actor else None,
        changes={"status": status.value, "priority": ticket_priority.value},
    )
    db.commit()
    db.refresh(ticket)
    return ticket


def transition_status(db: Session, ticket: Ticket, new_status: TicketStatus, actor: User | None) -> Ticket:
    old_status = TicketStatus(ticket.status)
    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise ValueError(f"Переход {old_status.value} -> {new_status.value} не разрешён")

    now = datetime.now(timezone.utc)

    was_paused = old_status in SLA_PAUSING_STATUSES
    will_be_paused = new_status in SLA_PAUSING_STATUSES
    if not was_paused and will_be_paused:
        ticket.sla_paused_at = now
    elif was_paused and not will_be_paused and ticket.sla_paused_at is not None:
        elapsed_minutes = int((now - ticket.sla_paused_at).total_seconds() // 60)
        ticket.sla_paused_minutes_total = (ticket.sla_paused_minutes_total or 0) + elapsed_minutes
        ticket.sla_paused_at = None

    # First resolution is fixed permanently - reopening never overwrites it
    # (docs/decisions.md: "SLA при переоткрытии заявки клиентом").
    if new_status == TicketStatus.RESOLVED and ticket.resolved_at is None:
        ticket.resolved_at = now
    if new_status == TicketStatus.CLOSED:
        ticket.closed_at = now

    ticket.status = new_status
    db.add(ticket)

    audit.record(
        db,
        entity_type="ticket",
        entity_id=ticket.id,
        action="status_changed",
        user_id=actor.id if actor else None,
        changes={"from": old_status.value, "to": new_status.value},
    )
    db.commit()
    db.refresh(ticket)
    return ticket


def update_ticket(db: Session, ticket: Ticket, payload: TicketUpdate, actor: User | None) -> Ticket:
    if payload.status is not None and TicketStatus(payload.status) != TicketStatus(ticket.status):
        transition_status(db, ticket, TicketStatus(payload.status), actor)

    changed: dict = {}

    if payload.assigned_engineer_id is not None and payload.assigned_engineer_id != ticket.assigned_engineer_id:
        changed["assigned_engineer_id"] = {"from": ticket.assigned_engineer_id, "to": payload.assigned_engineer_id}
        ticket.assigned_engineer_id = payload.assigned_engineer_id

    if payload.team_id is not None and payload.team_id != ticket.team_id:
        changed["team_id"] = {"from": ticket.team_id, "to": payload.team_id}
        ticket.team_id = payload.team_id

    if payload.category_id is not None:
        ticket.category_id = payload.category_id
    if payload.asset_id is not None:
        ticket.asset_id = payload.asset_id
    if payload.impact is not None:
        ticket.impact = payload.impact
    if payload.urgency is not None:
        ticket.urgency = payload.urgency

    if payload.manual_priority is not None:
        if not payload.manual_priority_reason:
            raise ValueError("При ручном приоритете нужно указать manual_priority_reason")
        changed["priority"] = {
            "from": ticket.priority,
            "to": payload.manual_priority.value,
            "reason": payload.manual_priority_reason,
        }
        ticket.priority = payload.manual_priority
        ticket.priority_override_reason = payload.manual_priority_reason
    elif payload.impact is not None and payload.urgency is not None:
        new_priority = priority_service.compute_priority(
            db, ImpactUrgencyLevel(ticket.impact), ImpactUrgencyLevel(ticket.urgency)
        )
        if new_priority != ticket.priority:
            changed["priority"] = {"from": ticket.priority, "to": new_priority.value}
            ticket.priority = new_priority
            ticket.priority_override_reason = None

    if changed:
        audit.record(
            db,
            entity_type="ticket",
            entity_id=ticket.id,
            action="updated",
            user_id=actor.id if actor else None,
            changes=changed,
        )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket
