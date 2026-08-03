"""Нагрузочная проверка (ТЗ р. 11, Этап 10: «нагрузочная проверка 500 заявок/день»).

Наполняет базу объёмом годовой эксплуатации при 500 заявках в день и
замеряет операции, которые сотрудник выполняет постоянно: открыть очередь,
поискать, открыть дашборд, открыть карточку. Проверяется именно чтение —
запись размазана по суткам и узким местом не бывает, а очередь и дашборд
дёргают каждые 30 секунд все открытые вкладки разом.

Запуск (внутри контейнера app):
    docker compose exec app python scripts/loadtest.py --days 30
    docker compose exec app python scripts/loadtest.py --days 365 --cleanup
"""

import argparse
import random
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/srv")

from sqlalchemy import func, text  # noqa: E402

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.message import Message  # noqa: E402
from app.models.ticket import Ticket  # noqa: E402
from app.models.user import User  # noqa: E402

MARKER = "[loadtest]"
TICKETS_PER_DAY = 500
SUBJECTS = [
    "Не открывается база 1С", "Не работает принтер", "Нет доступа к общей папке",
    "Медленно работает компьютер", "Не приходит почта", "Не подключается VPN",
    "Синий экран при загрузке", "Заканчивается место на диске",
]
BODIES = [
    "С утра не могу подключиться, выдаёт ошибку сети.",
    "Проблема повторяется каждый день после обеда.",
    "Перезагрузка не помогла, нужна помощь инженера.",
]


def seed(days: int) -> int:
    """Пишет напрямую через SQL, минуя сервисный слой: цель — получить объём
    данных, а не проверить бизнес-логику (её проверяют тесты). Через
    create_ticket() наполнение на 180 тысяч заявок шло бы часами."""
    db = SessionLocal()
    try:
        contact = db.query(Contact).first()
        engineers = [u.id for u in db.query(User).limit(5).all()] or [None]
        if contact is None:
            print("Нет ни одного контакта — сначала выполните сид.")
            return 0

        total = days * TICKETS_PER_DAY
        print(f"Наполнение: {total} заявок за {days} дн. ({TICKETS_PER_DAY}/день)…")
        start = time.perf_counter()
        now = datetime.now(timezone.utc)
        batch = 2000
        created = 0

        for offset in range(0, total, batch):
            rows = []
            messages = []
            for i in range(min(batch, total - offset)):
                index = offset + i
                created_at = now - timedelta(days=index // TICKETS_PER_DAY, minutes=index % 1440)
                status = random.choice(
                    [TicketStatus.CLOSED] * 7 + [TicketStatus.IN_PROGRESS, TicketStatus.NEW, TicketStatus.WAITING_CUSTOMER]
                )
                # SQLAlchemy's Enum(native_enum=False) persists member *names*
                # ("INCIDENT"), not values ("incident") - inserting values via
                # raw SQL produces rows the ORM then refuses to load.
                rows.append({
                    "type": TicketType.INCIDENT.name,
                    "channel": random.choice(list(Channel)).name,
                    "subject": f"{MARKER} {random.choice(SUBJECTS)}",
                    "organization_id": contact.organization_id,
                    "contact_id": contact.id,
                    "tariff_id": db.query(func.min(Ticket.tariff_id)).scalar() or 1,
                    "has_no_active_contract": False,
                    "priority": random.choice(list(Priority)).name,
                    "status": status.name,
                    "assigned_engineer_id": random.choice(engineers),
                    "created_at": created_at,
                    "updated_at": created_at,
                    "sla_reaction_due_at": created_at + timedelta(minutes=30),
                    "sla_resolution_due_at": created_at + timedelta(hours=4),
                    "sla_paused_minutes_total": 0,
                    "sla_paused_working_minutes_total": 0,
                })
            result = db.execute(
                text("""
                    INSERT INTO tickets (type, channel, subject, organization_id, contact_id, tariff_id,
                        has_no_active_contract, priority, status, assigned_engineer_id, created_at, updated_at,
                        sla_reaction_due_at, sla_resolution_due_at, sla_paused_minutes_total,
                        sla_paused_working_minutes_total)
                    VALUES (:type, :channel, :subject, :organization_id, :contact_id, :tariff_id,
                        :has_no_active_contract, :priority, :status, :assigned_engineer_id, :created_at, :updated_at,
                        :sla_reaction_due_at, :sla_resolution_due_at, :sla_paused_minutes_total,
                        :sla_paused_working_minutes_total)
                    RETURNING id
                """),
                rows,
            )
            # Два сообщения на заявку — примерно как в реальной переписке,
            # и это делает поиск по тексту честным.
            for (ticket_id,) in result.fetchall() if result.returns_rows else []:
                for direction in (MessageDirection.INBOUND, MessageDirection.OUTBOUND):
                    messages.append({
                        "ticket_id": ticket_id, "direction": direction.name,
                        "channel": Channel.EMAIL.name, "body": f"{MARKER} {random.choice(BODIES)}",
                    })
            if messages:
                db.execute(
                    text("""INSERT INTO messages (ticket_id, direction, channel, body)
                            VALUES (:ticket_id, :direction, :channel, :body)"""),
                    messages,
                )
            db.commit()
            created += len(rows)
            print(f"  {created}/{total}…", end="\r", flush=True)

        elapsed = time.perf_counter() - start
        print(f"\nНаполнено за {elapsed:.1f} с ({created / elapsed:.0f} заявок/с)")
        return created
    finally:
        db.close()


def measure(label: str, fn, runs: int = 5) -> float:
    timings = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        timings.append((time.perf_counter() - start) * 1000)
    median = statistics.median(timings)
    worst = max(timings)
    verdict = "ok" if median < 500 else ("медленно" if median < 2000 else "ПЛОХО")
    print(f"  {label:<46} {median:7.0f} мс (макс {worst:6.0f})  {verdict}")
    return median


def benchmark() -> None:
    from app.api.routers.tickets import _search_filter
    from app.services import reports

    db = SessionLocal()
    try:
        total = db.query(func.count(Ticket.id)).scalar()
        print(f"\nЗамеры на базе из {total} заявок:")

        measure("очередь, страница 1 (25 шт.)",
                lambda: db.query(Ticket).order_by(Ticket.created_at.desc()).limit(25).all())
        measure("очередь, глубокая страница (offset 10000)",
                lambda: db.query(Ticket).order_by(Ticket.created_at.desc()).limit(25).offset(10000).all())
        measure("счётчик для пагинации",
                lambda: db.query(func.count(Ticket.id)).scalar())
        measure("поиск по теме и переписке",
                lambda: _search_filter(db.query(Ticket), "принтер").limit(25).all())
        measure("фильтр по статусу + организации",
                lambda: db.query(Ticket).filter(
                    Ticket.status == TicketStatus.NEW.name, Ticket.organization_id == 1
                ).limit(25).all())
        measure("карточка заявки + переписка",
                lambda: db.query(Message).filter(
                    Message.ticket_id == db.query(func.max(Ticket.id)).scalar()
                ).all())

        today = datetime.now(timezone.utc).date()
        measure("отчёт за месяц", lambda: reports.get_overview(db, today - timedelta(days=30), today), runs=3)
        measure("отчёт клиенту за месяц",
                lambda: reports.get_client_report(db, 1, today - timedelta(days=30), today), runs=3)
    finally:
        db.close()


def cleanup() -> None:
    db = SessionLocal()
    try:
        print("Удаление нагрузочных данных…")
        db.execute(text(
            "DELETE FROM messages WHERE ticket_id IN (SELECT id FROM tickets WHERE subject LIKE :m)"
        ), {"m": f"{MARKER}%"})
        result = db.execute(text("DELETE FROM tickets WHERE subject LIKE :m"), {"m": f"{MARKER}%"})
        db.commit()
        print(f"Удалено заявок: {result.rowcount}")
        # Счётчик номеров (IDENTITY) назад не отматывается: следующая заявка
        # получит номер после нагрузочных. На поведение это не влияет, но
        # объясняет скачок в OH-<номер> — ещё одна причина не гонять
        # наполнение на боевой базе.
        print("Счётчик номеров заявок не сбрасывается — нумерация продолжится после нагрузочных.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Нагрузочная проверка SD")
    parser.add_argument("--days", type=int, default=30, help="сколько дней по 500 заявок наполнить")
    parser.add_argument("--cleanup", action="store_true", help="удалить нагрузочные данные и выйти")
    parser.add_argument("--no-seed", action="store_true", help="только замеры, без наполнения")
    args = parser.parse_args()

    if args.cleanup:
        cleanup()
    else:
        if not args.no_seed:
            seed(args.days)
        benchmark()
