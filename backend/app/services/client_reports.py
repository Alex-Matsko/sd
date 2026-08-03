"""Сформированные отчёты клиентам (ТЗ 9.2, ежемесячная выдача).

Отчёт хранится снимком (см. ClientReport): документ, отданный клиенту, не
должен меняться задним числом. Автоматическое формирование первого числа
только складывает отчёты в раздел — наружу без действия человека ничего
не уходит.
"""

import logging
from calendar import monthrange
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.client_report import ClientReport
from app.models.contract import Contract
from app.models.organization import Organization
from app.models.user import User
from app.services import reports

logger = logging.getLogger("app.client_reports")

MONTHS_RU = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def period_title(period_start: date, period_end: date) -> str:
    """«Июль 2026» для целого месяца, иначе диапазон датами.

    Заголовок документа, который читает клиент: «2026-07-01 — 2026-07-31»
    в шапке отчёта выглядит выгрузкой из базы, а не отчётом."""
    last_day = monthrange(period_start.year, period_start.month)[1]
    whole_month = (
        period_start.day == 1
        and period_end.day == last_day
        and period_start.year == period_end.year
        and period_start.month == period_end.month
    )
    if whole_month:
        return f"{MONTHS_RU[period_start.month - 1].capitalize()} {period_start.year}"
    return f"{period_start.strftime('%d.%m.%Y')} — {period_end.strftime('%d.%m.%Y')}"


def generate(
    db: Session,
    organization_id: int,
    period_start: date,
    period_end: date,
    actor: User | None = None,
    source: str = "manual",
) -> ClientReport:
    """Формирует отчёт и сохраняет снимок. Повторный вызов за тот же период
    перезаписывает снимок: это и есть «переформировать после исправления
    списаний», ради чего кнопка и нужна."""
    data = reports.get_client_report(db, organization_id, period_start, period_end)

    report = (
        db.query(ClientReport)
        .filter(
            ClientReport.organization_id == organization_id,
            ClientReport.period_start == period_start,
            ClientReport.period_end == period_end,
        )
        .first()
    )
    if report is None:
        report = ClientReport(
            organization_id=organization_id, period_start=period_start, period_end=period_end
        )
        db.add(report)

    report.data = data
    report.tickets_count = data["totals"]["tickets"]
    report.generated_at = datetime.now(timezone.utc)
    report.generated_by_user_id = actor.id if actor else None
    report.source = source
    # Переформированный отчёт снова считается неотправленным: у клиента на
    # руках старые цифры, и «отправлено» про них врало бы.
    report.sent_at = None
    report.sent_by_user_id = None

    db.commit()
    db.refresh(report)
    return report


def mark_sent(db: Session, report: ClientReport, actor: User) -> ClientReport:
    report.sent_at = datetime.now(timezone.utc)
    report.sent_by_user_id = actor.id
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _organizations_to_report(db: Session) -> list[int]:
    """Отчёт формируется по организациям с договором: без договора нет ни
    пакета часов, ни обязательств по SLA, и ежемесячный отчёт такому клиенту
    не отправляют."""
    rows = db.query(Contract.organization_id).distinct().all()
    return [row[0] for row in rows]


def generate_monthly_reports(db: Session, today: date | None = None) -> int:
    """Проход воркера: формирует отчёты за прошлый месяц.

    Формируется всё то, чего ещё нет — по одной организации за раз, чтобы
    падение на одном клиенте не оставило без отчётов остальных. Ничего не
    отправляется: раздел «Отчёты клиентам» наполняется, дальше решает
    человек.
    """
    today = today or datetime.now(timezone.utc).date()
    year, month = previous_month(today)
    period_start, period_end = month_bounds(year, month)

    # Проход выполняется на каждом тике воркера, а работает раз в месяц:
    # уже сформированные отчёты выбираются одним запросом, а не проверкой
    # на каждую организацию отдельно.
    already_done = {
        row[0]
        for row in db.query(ClientReport.organization_id).filter(
            ClientReport.period_start == period_start, ClientReport.period_end == period_end
        )
    }

    created = 0
    for organization_id in _organizations_to_report(db):
        if organization_id in already_done:
            continue
        try:
            generate(db, organization_id, period_start, period_end, actor=None, source="auto")
            created += 1
        except Exception:
            # Организацию могли удалить, договор — испортить. Один сломанный
            # клиент не должен оставить без отчётов всех остальных.
            db.rollback()
            organization = db.get(Organization, organization_id)
            logger.exception(
                "Отчёты клиентам: не удалось сформировать за %s для «%s»",
                period_title(period_start, period_end),
                organization.name if organization else organization_id,
            )
    if created:
        logger.info("Отчёты клиентам: сформировано %s за %s", created, period_title(period_start, period_end))
    return created
