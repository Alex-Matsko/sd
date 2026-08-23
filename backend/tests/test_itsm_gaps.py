"""Остатки по ITSM-практикам из аудита.

Три вещи, которых не хватало: удалить ошибочное списание было нельзя, доля
переоткрытых заявок нигде не считалась, а метки «повторяющаяся проблема» из
ТЗ р. 4 не существовало (при том что связь parent/child была сделана).
"""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routers.tickets import delete_time_entry
from app.core.enums import Channel, Priority, TicketStatus, TicketType, UserRole
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.schemas.time_entry import TimeEntryCreate
from app.services import reports
from app.services import tickets as tickets_service
from app.services import time_entries as time_entries_service


def _ticket(db: Session, contact: Contact, subject: str = "Заявка") -> Ticket:
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )


def _user(db: Session, role: UserRole, name: str) -> User:
    user = User(
        full_name=name, email=f"{name}@test.local".replace(" ", "-"),
        password_hash=hash_password("test1234"), role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# --- удаление ошибочного списания ---------------------------------------


def test_engineer_can_remove_his_own_mistaken_entry(db: Session, contact: Contact, engineer_user: User):
    """Списание, заведённое не на ту заявку, оставалось в счёте клиенту
    навсегда: запись можно было только исправить."""
    ticket = _ticket(db, contact)
    entry = time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=date.today(), duration_minutes=30), engineer_user
    )
    entry_id = entry.id

    delete_time_entry(ticket_id=ticket.id, entry_id=entry_id, db=db, actor=engineer_user)

    assert db.get(TimeEntry, entry_id) is None


def test_deletion_leaves_a_trace_in_the_history(db: Session, contact: Contact, engineer_user: User):
    """Это изменение суммы, которая уйдёт клиенту, — оно обязано быть
    прослеживаемым."""
    ticket = _ticket(db, contact)
    entry = time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=date.today(), duration_minutes=45), engineer_user
    )
    entry_id = entry.id

    delete_time_entry(ticket_id=ticket.id, entry_id=entry_id, db=db, actor=engineer_user)

    record = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "time_entry", AuditLog.entity_id == entry_id, AuditLog.action == "deleted")
        .one()
    )
    assert record.user_id == engineer_user.id
    assert record.changes["duration_minutes"] == 45


def test_engineer_cannot_remove_someone_elses_entry(db: Session, contact: Contact, engineer_user: User):
    ticket = _ticket(db, contact)
    entry = time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=date.today(), duration_minutes=30), engineer_user
    )
    other = _user(db, UserRole.ENGINEER, "Инженер Посторонний")

    with pytest.raises(HTTPException) as exc:
        delete_time_entry(ticket_id=ticket.id, entry_id=entry.id, db=db, actor=other)
    assert exc.value.status_code == 403


def test_manager_can_remove_anyones_entry(db: Session, contact: Contact, engineer_user: User):
    ticket = _ticket(db, contact)
    entry = time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=date.today(), duration_minutes=30), engineer_user
    )
    entry_id = entry.id
    manager = _user(db, UserRole.MANAGER, "Руководитель Списаний")

    delete_time_entry(ticket_id=ticket.id, entry_id=entry_id, db=db, actor=manager)
    assert db.get(TimeEntry, entry_id) is None


def test_freed_minutes_return_to_the_package(db: Session, contact: Contact, engineer_user: User, active_contract):
    """Пакет считается суммой существующих записей, поэтому удаление само
    возвращает минуты в остаток."""
    from app.services import billing

    ticket = _ticket(db, contact)
    entry = time_entries_service.create_time_entry(
        db, ticket, TimeEntryCreate(entry_date=date.today(), duration_minutes=120), engineer_user
    )
    today = date.today()
    used_before = billing.get_organization_usage(
        db, contact.organization_id, active_contract, today.year, today.month
    )["package_used_minutes"]
    assert used_before >= 120

    delete_time_entry(ticket_id=ticket.id, entry_id=entry.id, db=db, actor=engineer_user)

    used_after = billing.get_organization_usage(
        db, contact.organization_id, active_contract, today.year, today.month
    )["package_used_minutes"]
    assert used_after == used_before - 120


# --- переоткрытия (ITIL reopen rate) ------------------------------------


def test_reopening_is_counted(db: Session, contact: Contact):
    ticket = _ticket(db, contact, "Вернувшаяся проблема")
    assert ticket.reopen_count == 0

    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)

    db.refresh(ticket)
    assert ticket.reopen_count == 1

    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    db.refresh(ticket)
    assert ticket.reopen_count == 2


def test_a_straight_path_to_closed_counts_no_reopens(db: Session, contact: Contact):
    ticket = _ticket(db, contact, "Решено с первого раза")
    for step in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED):
        tickets_service.transition_status(db, ticket, step, actor=None)

    db.refresh(ticket)
    assert ticket.reopen_count == 0


def test_report_shows_the_reopen_rate(db: Session, contact: Contact):
    """«Решено» и «решено так, что не вернулось» — разные вещи, и в ITIL
    возвраты считают показателем качества решения."""
    clean = _ticket(db, contact, "Без возврата")
    for step in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED):
        tickets_service.transition_status(db, clean, step, actor=None)

    returned = _ticket(db, contact, "С возвратом")
    for step in (TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED):
        tickets_service.transition_status(db, returned, step, actor=None)

    today = date.today()
    sla = reports.get_overview(db, today, today, contact.organization_id)["sla"]

    assert sla["reopened_count"] == 1
    assert sla["reopened_pct"] == 50.0


# --- метка «повторяющаяся проблема» (ТЗ р. 4) ---------------------------


def test_recurring_problem_flag_can_be_set(db: Session, contact: Contact, engineer_user: User):
    ticket = _ticket(db, contact, "Каждый понедельник падает 1С")
    assert ticket.is_recurring_problem is False

    tickets_service.update_ticket(db, ticket, TicketUpdate(is_recurring_problem=True), actor=engineer_user)

    db.refresh(ticket)
    assert ticket.is_recurring_problem is True


def test_setting_the_flag_lands_in_the_history(db: Session, contact: Contact, engineer_user: User):
    """Это решение о том, что случай не разовый, — по нему потом ищут
    связанные обращения."""
    ticket = _ticket(db, contact)
    tickets_service.update_ticket(db, ticket, TicketUpdate(is_recurring_problem=True), actor=engineer_user)

    record = (
        db.query(AuditLog)
        .filter(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket.id, AuditLog.action == "updated")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert record.changes["is_recurring_problem"] == {"from": False, "to": True}
