"""Кто какие заявки видит (ТЗ р. 6).

Одна точка решения на весь сотруднический API — по той же причине, что и
`portal.visible_tickets_query` для клиента: правило «что моё» должно быть в
одном месте, которое легко проверить, а не выводиться заново в каждом
эндпоинте. Раньше ограничения не было вовсе: инженер читал переписку и
вложения по всем организациям и мог править чужие заявки.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.models.ticket import Ticket
from app.models.user import TeamMembership, User

# Диспетчер ведёт всю очередь, руководитель и администратор — тем более
# (ТЗ р. 6). Ограничение касается только инженера.
FULL_QUEUE_ROLES = {UserRole.DISPATCHER, UserRole.MANAGER, UserRole.ADMIN}


def sees_full_queue(user: User) -> bool:
    return UserRole(user.role) in FULL_QUEUE_ROLES


def team_ids_of(db: Session, user: User) -> list[int]:
    return [row[0] for row in db.query(TeamMembership.team_id).filter(TeamMembership.user_id == user.id)]


def visible_tickets_query(db: Session, user: User):
    """Заявки, доступные сотруднику.

    Инженеру — «свои и групповые» по ТЗ, плюс нераспределённый остаток общей
    очереди. Последнее не послабление, а условие работоспособности: ТЗ 4.4
    требует «самоназначение инженером», а взять в работу заявку, которой не
    видно, невозможно. Как только заявка назначена на другого инженера или
    ушла в чужую команду, она из выдачи исчезает.
    """
    query = db.query(Ticket)
    if sees_full_queue(user):
        return query

    conditions = [Ticket.assigned_engineer_id == user.id]
    team_ids = team_ids_of(db, user)
    if team_ids:
        conditions.append(Ticket.team_id.in_(team_ids))
    conditions.append(and_unassigned())
    return query.filter(or_(*conditions))


def and_unassigned():
    """Общая очередь: ни исполнителя, ни команды."""
    from sqlalchemy import and_

    return and_(Ticket.assigned_engineer_id.is_(None), Ticket.team_id.is_(None))


def can_see(db: Session, user: User, ticket: Ticket) -> bool:
    if sees_full_queue(user):
        return True
    if ticket.assigned_engineer_id == user.id:
        return True
    if ticket.team_id is not None and ticket.team_id in team_ids_of(db, user):
        return True
    return ticket.assigned_engineer_id is None and ticket.team_id is None
