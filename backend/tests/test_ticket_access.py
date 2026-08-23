"""Видимость заявок сотруднику (ТЗ р. 6).

До этого ограничения не было вовсе: инженер читал переписку и вложения по
всем организациям и мог править чужие заявки. Проверка стоит в единственной
точке получения заявки, поэтому здесь важно убедиться, что она действительно
срабатывает и что диспетчеру с руководителем ничего не сломали.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routers.tickets import _get_ticket_or_404, get_ticket_stats, list_tickets
from app.core.enums import Channel, Priority, TicketType, UserRole
from app.core.security import hash_password
from app.models.contact import Contact
from app.models.team import Team
from app.models.ticket import Ticket
from app.models.user import TeamMembership, User
from app.schemas.ticket import TicketCreate
from app.services import ticket_access
from app.services import tickets as tickets_service


def _user(db: Session, role: UserRole, name: str) -> User:
    user = User(
        full_name=name, email=f"{name}@test.local".replace(" ", "-"),
        password_hash=hash_password("test1234"), role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _ticket(db: Session, contact: Contact, subject: str, **fields) -> Ticket:
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )
    # Маршрутизация могла что-то назначить сама — тест задаёт расклад явно.
    ticket.assigned_engineer_id = fields.get("assigned_engineer_id")
    ticket.team_id = fields.get("team_id")
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


@pytest.fixture()
def engineer(db: Session) -> User:
    return _user(db, UserRole.ENGINEER, "Инженер Видимость")


@pytest.fixture()
def other_engineer(db: Session) -> User:
    return _user(db, UserRole.ENGINEER, "Инженер Чужой")


# --- инженер ------------------------------------------------------------


def test_engineer_sees_own_ticket(db: Session, contact: Contact, engineer: User):
    ticket = _ticket(db, contact, "Моя заявка", assigned_engineer_id=engineer.id)
    assert ticket_access.can_see(db, engineer, ticket)


def test_engineer_does_not_see_a_ticket_assigned_to_someone_else(
    db: Session, contact: Contact, engineer: User, other_engineer: User
):
    ticket = _ticket(db, contact, "Чужая заявка", assigned_engineer_id=other_engineer.id)
    assert not ticket_access.can_see(db, engineer, ticket)


def test_engineer_sees_tickets_of_his_team(db: Session, contact: Contact, engineer: User):
    team = Team(name="Команда видимости")
    db.add(team)
    db.commit()
    db.add(TeamMembership(team_id=team.id, user_id=engineer.id))
    db.commit()

    ticket = _ticket(db, contact, "Командная заявка", team_id=team.id)
    assert ticket_access.can_see(db, engineer, ticket)


def test_engineer_does_not_see_another_teams_ticket(db: Session, contact: Contact, engineer: User):
    foreign = Team(name="Чужая команда")
    db.add(foreign)
    db.commit()

    ticket = _ticket(db, contact, "Заявка чужой команды", team_id=foreign.id)
    assert not ticket_access.can_see(db, engineer, ticket)


def test_engineer_sees_the_unassigned_queue(db: Session, contact: Contact, engineer: User):
    """ТЗ 4.4 требует самоназначение инженером. Взять в работу заявку,
    которой не видно, невозможно — поэтому нераспределённый остаток общей
    очереди инженеру виден намеренно."""
    ticket = _ticket(db, contact, "Ничья заявка")
    assert ticket_access.can_see(db, engineer, ticket)


# --- остальные роли -----------------------------------------------------


@pytest.mark.parametrize("role", [UserRole.DISPATCHER, UserRole.MANAGER, UserRole.ADMIN])
def test_dispatcher_and_above_see_everything(db: Session, contact: Contact, other_engineer: User, role):
    staff = _user(db, role, f"Сотрудник {role.value}")
    ticket = _ticket(db, contact, "Чужая заявка", assigned_engineer_id=other_engineer.id)
    assert ticket_access.can_see(db, staff, ticket)


# --- через эндпоинты ----------------------------------------------------


def test_lookup_hides_a_foreign_ticket_as_404(
    db: Session, contact: Contact, engineer: User, other_engineer: User
):
    """404, а не 403: по разнице кодов перебираются существующие номера."""
    ticket = _ticket(db, contact, "Чужая заявка", assigned_engineer_id=other_engineer.id)

    with pytest.raises(HTTPException) as exc:
        _get_ticket_or_404(db, ticket.id, engineer)
    assert exc.value.status_code == 404


def test_queue_excludes_foreign_tickets(db: Session, contact: Contact, engineer: User, other_engineer: User):
    mine = _ticket(db, contact, "Заявка инженера", assigned_engineer_id=engineer.id)
    foreign = _ticket(db, contact, "Заявка коллеги", assigned_engineer_id=other_engineer.id)

    class _Response:
        headers: dict = {}

    visible = list_tickets(response=_Response(), db=db, actor=engineer, limit=200)
    ids = {t.id for t in visible}

    assert mine.id in ids
    assert foreign.id not in ids


def test_dashboard_counts_match_what_the_engineer_can_open(
    db: Session, contact: Contact, engineer: User, other_engineer: User
):
    """Иначе на дашборде цифры по всей компании, а в списке под ними — свои
    заявки, и счётчики читаются как ошибка."""
    before = get_ticket_stats(db=db, actor=engineer)["open_total"]

    _ticket(db, contact, "Чужая новая", assigned_engineer_id=other_engineer.id)
    assert get_ticket_stats(db=db, actor=engineer)["open_total"] == before

    _ticket(db, contact, "Моя новая", assigned_engineer_id=engineer.id)
    assert get_ticket_stats(db=db, actor=engineer)["open_total"] == before + 1


def test_workload_widget_is_for_the_full_queue_roles_only(db: Session, engineer: User):
    """Чужая нагрузка инженеру не нужна, а по урезанной области виджет
    показывал бы его одного."""
    assert get_ticket_stats(db=db, actor=engineer)["workload"] == []
