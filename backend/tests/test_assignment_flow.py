"""Назначение исполнителя и статус (ТЗ 4.2, 4.4).

Раньше диспетчер назначал инженера, а заявка оставалась «Новой»: очередь
новых наполнялась уже разобранными заявками, и статус приходилось менять
вторым действием, о котором легко забыть. Теперь статус следует за
назначением — так же, как это делает маршрутизация при создании заявки.
"""

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, TicketStatus, TicketType, UserRole
from app.core.security import hash_password
from app.models.contact import Contact
from app.models.team import Team
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services import tickets as tickets_service


def _make(db: Session, contact: Contact, subject: str = "Заявка") -> Ticket:
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PHONE, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )
    # Маршрутизация могла назначить сама — тесту нужна именно «Новая».
    ticket.assigned_engineer_id = None
    ticket.team_id = None
    ticket.status = TicketStatus.NEW
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@pytest.fixture()
def engineer(db: Session) -> User:
    user = User(
        full_name="Инженер Назначений", email="assign-engineer@test.local",
        password_hash=hash_password("test1234"), role=UserRole.ENGINEER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_assigning_an_engineer_moves_new_to_assigned(db: Session, contact: Contact, engineer: User):
    ticket = _make(db, contact)
    assert TicketStatus(ticket.status) == TicketStatus.NEW

    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer.id), actor=None)

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.ASSIGNED


def test_assigning_a_team_also_moves_to_assigned(db: Session, contact: Contact):
    """Заявка, отданная группе, тоже перестаёт быть новой: её уже разобрали."""
    team = Team(name="Группа назначений")
    db.add(team)
    db.commit()
    ticket = _make(db, contact)

    tickets_service.update_ticket(db, ticket, TicketUpdate(team_id=team.id), actor=None)

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.ASSIGNED


def test_removing_the_assignee_returns_the_ticket_to_the_queue(db: Session, contact: Contact, engineer: User):
    """Заявка без исполнителя со статусом «Назначена» — противоречие: она
    снова в общей очереди, и видеть её должны все."""
    ticket = _make(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer.id), actor=None)

    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=None), actor=None)

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.NEW


def test_work_in_progress_is_not_disturbed_by_reassignment(db: Session, contact: Contact, engineer: User):
    """Смена исполнителя у заявки в работе не должна откатывать её статус —
    это стёрло бы ход работы."""
    ticket = _make(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer.id), actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    other = User(
        full_name="Инженер Второй", email="assign-second@test.local",
        password_hash=hash_password("test1234"), role=UserRole.ENGINEER,
    )
    db.add(other)
    db.commit()
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=other.id), actor=None)

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.IN_PROGRESS


def test_unassigning_a_ticket_in_progress_keeps_it_in_progress(db: Session, contact: Contact, engineer: User):
    ticket = _make(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer.id), actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=None), actor=None)

    db.refresh(ticket)
    assert TicketStatus(ticket.status) == TicketStatus.IN_PROGRESS


def test_status_change_is_recorded_in_history(db: Session, contact: Contact, engineer: User):
    """Автоматический переход должен быть виден в истории так же, как
    ручной: иначе непонятно, почему статус изменился сам."""
    from app.models.audit import AuditLog

    ticket = _make(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer.id), actor=None)

    records = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket.id, AuditLog.action == "status_changed")
        .all()
    )
    assert any(r.changes == {"from": "new", "to": "assigned"} for r in records)


def test_client_sees_the_assignee_in_the_portal(db: Session, contact: Contact, engineer: User):
    """Боты сообщали клиенту, кто ведёт заявку, а в кабинете было не видно —
    клиент не знал, к кому обращаться."""
    from app.api.routers.portal import _engineer_names, _to_read

    ticket = _make(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(assigned_engineer_id=engineer.id), actor=None)
    db.refresh(ticket)

    view = _to_read(ticket, _engineer_names(db, [ticket]).get(ticket.assigned_engineer_id))
    assert view.assigned_engineer_name == engineer.full_name
