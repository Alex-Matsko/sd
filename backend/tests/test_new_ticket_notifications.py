"""Уведомления о новых заявках (ТЗ р. 8).

Маршрутизация назначает исполнителя прямо при создании заявки, но
уведомление отправлялось только при ручной смене исполнителя в карточке. В
результате первым сигналом о заявке становилось предупреждение о 75% SLA —
инженер узнавал о работе, когда срок уже горел. Нераспределённые заявки не
видел вообще никто: из почты, ботов, портала и по пропущенным звонкам они
попадали в общую очередь молча.
"""

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, NotificationType, Priority, TicketType, UserRole
from app.core.security import hash_password
from app.models.contact import Contact
from app.models.notification import Notification
from app.models.routing import RoutingRule
from app.models.team import Team
from app.models.ticket import Ticket
from app.models.user import TeamMembership, User
from app.schemas.ticket import TicketCreate
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


def _make(db: Session, contact: Contact, subject="Новая заявка", priority=Priority.P3, actor=None) -> Ticket:
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL, subject=subject,
            manual_priority=priority, manual_priority_reason="test",
        ),
        actor=actor,
    )


def _notes(db: Session, ticket: Ticket) -> list[Notification]:
    return db.query(Notification).filter(Notification.ticket_id == ticket.id).all()


@pytest.fixture()
def dispatcher(db: Session) -> User:
    return _user(db, UserRole.DISPATCHER, "Диспетчер Новых")


def test_unassigned_ticket_reaches_the_dispatcher(db: Session, contact: Contact, dispatcher: User):
    """Из почты, ботов и портала заявки попадают в общую очередь — раньше о
    них не узнавал никто."""
    ticket = _make(db, contact)
    assert ticket.assigned_engineer_id is None and ticket.team_id is None

    notes = _notes(db, ticket)
    assert [n.user_id for n in notes] == [dispatcher.id]
    assert notes[0].type == NotificationType.TICKET_UNASSIGNED
    assert "без исполнителя" in notes[0].title


def test_auto_assigned_ticket_reaches_the_engineer(db: Session, contact: Contact, dispatcher: User):
    """Правило «организация → выделенный инженер» срабатывает при создании,
    и до этого исправления инженер о заявке не узнавал."""
    engineer = _user(db, UserRole.ENGINEER, "Инженер Выделенный")
    db.add(
        RoutingRule(
            rule_type="organization_to_engineer", order=1, is_active=True,
            organization_id=contact.organization_id, target_engineer_id=engineer.id,
        )
    )
    db.commit()

    ticket = _make(db, contact, "Заявка по правилу")

    assert ticket.assigned_engineer_id == engineer.id
    notes = _notes(db, ticket)
    assert [n.user_id for n in notes] == [engineer.id]
    assert notes[0].type == NotificationType.TICKET_ASSIGNED
    assert "на вас" in notes[0].title


def test_team_ticket_reaches_the_whole_group(db: Session, contact: Contact, dispatcher: User):
    """ТЗ 4.4 допускает самоназначение внутри группы: о работе должны узнать
    те, кто её возьмёт, а не только руководитель."""
    lead = _user(db, UserRole.ENGINEER, "Руководитель Группы")
    member = _user(db, UserRole.ENGINEER, "Инженер Группы")
    team = Team(name="Группа уведомлений", lead_user_id=lead.id)
    db.add(team)
    db.commit()
    db.add(TeamMembership(team_id=team.id, user_id=member.id))
    db.commit()

    # Категория заводится тестом, а не берётся из сида: справочник у
    # заказчика настраивается под себя, и опираться на его содержимое
    # проверка маршрутизации не должна.
    from app.models.category import Category

    category = Category(name="Категория уведомлений")
    db.add(category)
    db.commit()
    db.add(
        RoutingRule(
            rule_type="category_to_team", order=1, is_active=True,
            category_id=category.id, target_team_id=team.id,
        )
    )
    db.commit()

    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL,
            subject="Заявка на группу", category_id=category.id,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )

    assert ticket.team_id == team.id
    recipients = {n.user_id for n in _notes(db, ticket)}
    assert recipients == {lead.id, member.id}


def test_the_author_is_not_notified_about_his_own_ticket(db: Session, contact: Contact):
    """Диспетчер, заводящий заявку по звонку, не должен получать уведомление
    о ней сам — это шум."""
    dispatcher = _user(db, UserRole.DISPATCHER, "Диспетчер Автор")

    ticket = _make(db, contact, "Заявка по звонку", actor=dispatcher)

    assert [n.user_id for n in _notes(db, ticket)] == []


@pytest.mark.parametrize("priority,expected", [(Priority.P1, True), (Priority.P2, True), (Priority.P3, False)])
def test_urgent_priority_is_visible_in_the_headline(
    db: Session, contact: Contact, dispatcher: User, priority, expected
):
    """Авария не должна выглядеть в колокольчике как рядовое обращение."""
    ticket = _make(db, contact, "Упал сервер", priority=priority)

    title = _notes(db, ticket)[0].title
    assert title.startswith(f"[{priority.value}]") is expected


def test_notification_names_the_ticket(db: Session, contact: Contact, dispatcher: User):
    """Из колокольчика должно быть понятно, о какой заявке речь, без перехода."""
    ticket = _make(db, contact, "Не открывается база 1С")

    title = _notes(db, ticket)[0].title
    assert ticket.display_number in title
    assert "Не открывается база 1С" in title


def test_the_first_message_is_not_a_reply(db: Session, contact: Contact, dispatcher: User):
    """Создание заявки с описанием давало инженеру сразу два уведомления —
    «новая заявка на вас» и «клиент ответил» про одно и то же. Первое
    сообщение заявки это её текст, а не ответ."""
    engineer = _user(db, UserRole.ENGINEER, "Инженер Первого Сообщения")
    db.add(
        RoutingRule(
            rule_type="organization_to_engineer", order=1, is_active=True,
            organization_id=contact.organization_id, target_engineer_id=engineer.id,
        )
    )
    db.commit()

    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.EMAIL,
            subject="Упал сервер", manual_priority=Priority.P1, manual_priority_reason="авария",
            initial_message="Сервер недоступен с утра",
        ),
        actor=None,
    )

    types = [n.type for n in _notes(db, ticket)]
    assert types == [NotificationType.TICKET_ASSIGNED]


def test_a_real_reply_still_notifies(db: Session, contact: Contact, dispatcher: User):
    """Проверка не должна заглушить настоящий ответ клиента."""
    from app.core.enums import MessageDirection
    from app.schemas.message import MessageCreate
    from app.services import messages as messages_service

    engineer = _user(db, UserRole.ENGINEER, "Инженер Настоящего Ответа")
    ticket = _make(db, contact, "Заявка с перепиской")
    ticket.assigned_engineer_id = engineer.id
    db.add(ticket)
    db.commit()

    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="Первое сообщение"),
        author_contact=contact,
    )
    messages_service.add_message(
        db, ticket, MessageCreate(direction=MessageDirection.INBOUND, body="А теперь ещё хуже"),
        author_contact=contact,
    )

    replies = [n for n in _notes(db, ticket) if n.type == NotificationType.CUSTOMER_REPLIED]
    assert len(replies) == 1
    assert replies[0].user_id == engineer.id
