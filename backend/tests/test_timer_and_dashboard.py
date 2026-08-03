"""Таймер работы над заявкой (ТЗ 8.2) и счётчики дашборда (ТЗ 8.3).

Обе вещи легко «работают» на глаз и врут в цифрах, поэтому проверяются
именно граничные случаи: мис-клик по таймеру, переключение между заявками,
и то, что счётчики считают по всей очереди, а не по видимой странице.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, TicketStatus, TicketType
from app.models.active_timer import ActiveTimer
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.ticket import TicketCreate
from app.services import time_entries as time_entries_service
from app.services import tickets as tickets_service


def _make(db: Session, contact: Contact, subject: str = "Заявка для таймера") -> Ticket:
    return tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id, type=TicketType.INCIDENT, channel=Channel.PHONE, subject=subject,
            manual_priority=Priority.P3, manual_priority_reason="test",
        ),
        actor=None,
    )


def _backdate_timer(db: Session, engineer: User, seconds: int) -> None:
    """Отматывает старт таймера назад — иначе тест пришлось бы усыплять
    на минуту, чтобы перешагнуть порог списания."""
    timer = db.query(ActiveTimer).filter(ActiveTimer.user_id == engineer.id).one()
    timer.started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    db.add(timer)
    db.commit()


# --- таймер -------------------------------------------------------------


def test_timer_books_time_on_stop(db: Session, contact: Contact, engineer_user: User):
    ticket = _make(db, contact)
    time_entries_service.start_timer(db, ticket, engineer_user)
    _backdate_timer(db, engineer_user, 90)

    entry = time_entries_service.stop_timer(db, engineer_user)

    assert entry is not None
    # 90 секунд округляются вверх до 2 минут: недосписать время клиенту хуже,
    # чем списать лишнюю минуту.
    assert entry.duration_minutes == 2
    assert entry.ticket_id == ticket.id
    # Запись подписана: в отчёте клиенту её надо отличать от введённой руками.
    assert entry.comment == time_entries_service.TIMER_COMMENT
    assert time_entries_service.get_active_timer(db, engineer_user) is None


def test_misclick_under_a_minute_books_nothing(db: Session, contact: Contact, engineer_user: User):
    ticket = _make(db, contact)
    time_entries_service.start_timer(db, ticket, engineer_user)
    _backdate_timer(db, engineer_user, 5)

    entry = time_entries_service.stop_timer(db, engineer_user)

    assert entry is None
    assert time_entries_service.get_active_timer(db, engineer_user) is None
    # Главное — что в отчёте клиенту не появилось записи на ноль минут.
    db.refresh(ticket)
    assert len(ticket.time_entries) == 0


def test_starting_second_timer_banks_the_first(db: Session, contact: Contact, engineer_user: User):
    first = _make(db, contact, "Первая заявка")
    second = _make(db, contact, "Вторая заявка")

    time_entries_service.start_timer(db, first, engineer_user)
    # 115, а не 120: время округляется вверх, и ровно на границе минуты
    # лишние миллисекунды теста дали бы третью минуту.
    _backdate_timer(db, engineer_user, 115)
    time_entries_service.start_timer(db, second, engineer_user)

    db.refresh(first)
    # Работа по первой заявке не должна пропасть молча.
    assert [e.duration_minutes for e in first.time_entries] == [2]
    timer = time_entries_service.get_active_timer(db, engineer_user)
    assert timer is not None and timer.ticket_id == second.id


def test_restarting_the_same_ticket_does_not_reset_elapsed(db: Session, contact: Contact, engineer_user: User):
    ticket = _make(db, contact)
    timer = time_entries_service.start_timer(db, ticket, engineer_user)
    started_at = timer.started_at

    again = time_entries_service.start_timer(db, ticket, engineer_user)

    # Повторное нажатие по той же заявке — это, скорее всего, вторая вкладка,
    # а не намерение обнулить накопленное время.
    assert again.started_at == started_at
    assert db.query(ActiveTimer).filter(ActiveTimer.user_id == engineer_user.id).count() == 1


def test_stop_without_running_timer_is_harmless(db: Session, engineer_user: User):
    assert time_entries_service.stop_timer(db, engineer_user) is None


def test_timer_survives_ticket_deletion(db: Session, contact: Contact, engineer_user: User):
    """Заявку могли удалить, пока таймер шёл. Списывать время некуда, но и
    падать нельзя — таймер должен просто сняться."""
    ticket = _make(db, contact)
    time_entries_service.start_timer(db, ticket, engineer_user)
    _backdate_timer(db, engineer_user, 120)
    db.delete(ticket)
    db.commit()

    assert time_entries_service.stop_timer(db, engineer_user) is None
    assert time_entries_service.get_active_timer(db, engineer_user) is None


# --- счётчики дашборда --------------------------------------------------


@pytest.fixture()
def stats(db: Session):
    """Вызывает эндпоинт напрямую с сессией теста: через HTTP-клиент запрос
    ушёл бы в другую сессию и не увидел данных, созданных внутри savepoint."""
    from app.api.routers.tickets import get_ticket_stats

    def _stats() -> dict:
        return get_ticket_stats(db=db, _=None)

    return _stats


def test_at_risk_today_counts_deadlines_before_midnight(db: Session, contact: Contact, stats):
    ticket = _make(db, contact, "Срок сегодня")
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    ticket.sla_resolution_due_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    db.add(ticket)
    db.commit()

    before = stats()["at_risk_today"]

    later = _make(db, contact, "Срок послезавтра")
    tickets_service.transition_status(db, later, TicketStatus.IN_PROGRESS, actor=None)
    later.sla_resolution_due_at = datetime.now(timezone.utc) + timedelta(days=2)
    db.add(later)
    db.commit()

    # Заявка с дальним сроком не должна попадать в «риски сегодня».
    assert stats()["at_risk_today"] == before


def test_overdue_and_at_risk_do_not_overlap(db: Session, contact: Contact, stats):
    ticket = _make(db, contact, "Просрочена")
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    ticket.sla_resolution_due_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.add(ticket)
    db.commit()

    result = stats()
    at_risk_before = result["at_risk_today"]

    # Просроченная заявка считается только как нарушение SLA: показывать её
    # ещё и в «истекает сегодня» значило бы дважды считать одну проблему.
    assert result["overdue"] >= 1
    assert stats()["at_risk_today"] == at_risk_before


def test_closed_ticket_leaves_the_risk_counters(db: Session, contact: Contact, stats):
    ticket = _make(db, contact, "Скоро закроем")
    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    ticket.sla_resolution_due_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    db.add(ticket)
    db.commit()
    with_open = stats()["at_risk_today"]

    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    assert stats()["at_risk_today"] == with_open - 1


def test_week_flow_covers_seven_days_with_both_series(db: Session, contact: Contact, stats):
    result = stats()
    flow = result["week_flow"]

    assert len(flow) == 7
    assert [d["date"] for d in flow] == sorted(d["date"] for d in flow)
    assert flow[-1]["date"] == date.today().isoformat()
    # Обе серии обязаны присутствовать на каждом дне, включая пустые: иначе
    # график на фронте молча пропустит день.
    assert all("created" in d and "closed" in d for d in flow)


def test_week_flow_counts_created_and_closed(db: Session, contact: Contact, stats):
    before = stats()["week_flow"][-1]

    ticket = _make(db, contact, "Создана и закрыта сегодня")
    after_create = stats()["week_flow"][-1]
    assert after_create["created"] == before["created"] + 1
    assert after_create["closed"] == before["closed"]

    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    after_close = stats()["week_flow"][-1]
    assert after_close["closed"] == before["closed"] + 1


def test_workload_counts_only_open_tickets(db: Session, contact: Contact, engineer_user: User, stats):
    def mine() -> int:
        rows = stats()["workload"]
        return next((r["open_tickets"] for r in rows if r["engineer_name"] == engineer_user.full_name), 0)

    ticket = _make(db, contact, "Назначенная заявка")
    ticket.assigned_engineer_id = engineer_user.id
    db.add(ticket)
    db.commit()
    assigned = mine()
    assert assigned >= 1

    tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    tickets_service.transition_status(db, ticket, TicketStatus.CLOSED, actor=None)

    # Закрытая заявка перестаёт быть нагрузкой — иначе список загрузки
    # со временем превращается в счётчик стажа.
    assert mine() == assigned - 1
