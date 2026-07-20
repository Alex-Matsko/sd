"""Idempotent bootstrap data: default tariff/calendar, priority matrix, RF
holidays, public email domain registry, first admin user. Safe to run on every
container start (see Dockerfile) - everything is check-then-insert."""

from datetime import date, time

from app.config import settings
from app.core.enums import ImpactUrgencyLevel, Priority, UserRole
from app.core.security import hash_password
from app.db import SessionLocal
from app.models.calendar import BusinessCalendar, BusinessCalendarWindow, Holiday
from app.models.organization import PublicEmailDomain
from app.models.priority import ImpactUrgencyRule
from app.models.tariff import Tariff, TariffSlaRule
from app.models.user import User

# Nominal federal-holiday dates for RF, calendar year of first deploy. The
# government shifts a few of these around weekends via yearly decree - verify
# and adjust through the /holidays API before relying on them for SLA pauses.
RF_HOLIDAYS_2026 = [
    (date(2026, 1, 1), "Новый год"),
    (date(2026, 1, 2), "Новогодние каникулы"),
    (date(2026, 1, 7), "Рождество Христово"),
    (date(2026, 2, 23), "День защитника Отечества"),
    (date(2026, 3, 8), "Международный женский день"),
    (date(2026, 5, 1), "Праздник Весны и Труда"),
    (date(2026, 5, 9), "День Победы"),
    (date(2026, 6, 12), "День России"),
    (date(2026, 11, 4), "День народного единства"),
]

PUBLIC_EMAIL_DOMAINS = [
    "gmail.com",
    "yandex.ru",
    "yandex.com",
    "mail.ru",
    "bk.ru",
    "list.ru",
    "inbox.ru",
    "rambler.ru",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "protonmail.com",
]

# Standard 3x3 Impact x Urgency -> Priority matrix (section 4.1), editable via
# PUT /priority-matrix.
DEFAULT_PRIORITY_MATRIX = [
    (ImpactUrgencyLevel.HIGH, ImpactUrgencyLevel.HIGH, Priority.P1),
    (ImpactUrgencyLevel.HIGH, ImpactUrgencyLevel.MEDIUM, Priority.P2),
    (ImpactUrgencyLevel.HIGH, ImpactUrgencyLevel.LOW, Priority.P3),
    (ImpactUrgencyLevel.MEDIUM, ImpactUrgencyLevel.HIGH, Priority.P2),
    (ImpactUrgencyLevel.MEDIUM, ImpactUrgencyLevel.MEDIUM, Priority.P3),
    (ImpactUrgencyLevel.MEDIUM, ImpactUrgencyLevel.LOW, Priority.P4),
    (ImpactUrgencyLevel.LOW, ImpactUrgencyLevel.HIGH, Priority.P3),
    (ImpactUrgencyLevel.LOW, ImpactUrgencyLevel.MEDIUM, Priority.P4),
    (ImpactUrgencyLevel.LOW, ImpactUrgencyLevel.LOW, Priority.P4),
]

# Placeholder SLA minutes for the default fallback tariff - adjust per real
# tariffs via PUT /tariffs/{id}/sla-rules.
DEFAULT_SLA_MINUTES = {
    Priority.P1: (30, 240),
    Priority.P2: (60, 480),
    Priority.P3: (240, 1440),
    Priority.P4: (480, 2880),
}


def seed(db) -> None:
    if db.query(BusinessCalendar).filter(BusinessCalendar.name == "Стандартный 5x8").first() is None:
        calendar = BusinessCalendar(name="Стандартный 5x8", timezone="Europe/Moscow", is_24x7=False, observes_holidays=True)
        db.add(calendar)
        db.flush()
        for weekday in range(5):  # Mon-Fri
            db.add(
                BusinessCalendarWindow(
                    calendar_id=calendar.id, weekday=weekday, start_time=time(9, 0), end_time=time(18, 0)
                )
            )
    else:
        calendar = db.query(BusinessCalendar).filter(BusinessCalendar.name == "Стандартный 5x8").first()

    if db.query(Tariff).filter(Tariff.code == settings.default_tariff_code).first() is None:
        tariff = Tariff(
            code=settings.default_tariff_code,
            name="Базовый (по умолчанию)",
            description="Фолбэк-тариф для заявок организаций без активного договора",
            business_calendar_id=calendar.id,
        )
        db.add(tariff)
        db.flush()
        for priority, (reaction, resolution) in DEFAULT_SLA_MINUTES.items():
            db.add(
                TariffSlaRule(
                    tariff_id=tariff.id,
                    priority=priority,
                    reaction_time_minutes=reaction,
                    resolution_time_minutes=resolution,
                )
            )

    if db.query(ImpactUrgencyRule).count() == 0:
        for impact, urgency, priority in DEFAULT_PRIORITY_MATRIX:
            db.add(ImpactUrgencyRule(impact=impact, urgency=urgency, priority=priority))

    existing_holiday_dates = {h.holiday_date for h in db.query(Holiday).all()}
    for holiday_date, name in RF_HOLIDAYS_2026:
        if holiday_date not in existing_holiday_dates:
            db.add(Holiday(holiday_date=holiday_date, name=name))

    existing_domains = {d.domain for d in db.query(PublicEmailDomain).all()}
    for domain in PUBLIC_EMAIL_DOMAINS:
        if domain not in existing_domains:
            db.add(PublicEmailDomain(domain=domain))

    if db.query(User).filter(User.email == settings.seed_admin_email).first() is None:
        db.add(
            User(
                full_name="Администратор",
                email=settings.seed_admin_email,
                password_hash=hash_password(settings.seed_admin_password),
                role=UserRole.ADMIN,
            )
        )
        print(f"[seed] Создан администратор {settings.seed_admin_email} - смените пароль после первого входа")

    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
