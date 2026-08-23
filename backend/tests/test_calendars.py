"""Рабочий календарь и праздники (ТЗ 4.3).

По этому справочнику считаются сроки SLA, и до появления интерфейса он был
доступен только через API: рабочие часы созданного календаря вообще нельзя
было изменить, а праздники завели на один 2026 год. С 1 января 2027 система
считала бы новогодние каникулы рабочими днями.
"""

from datetime import date, time

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.routers.calendars import create_holidays, delete_holiday, replace_calendar_windows
from app.models.calendar import BusinessCalendar, BusinessCalendarWindow, Holiday
from app.schemas.calendar import CalendarWindowCreate, HolidayCreate


@pytest.fixture()
def calendar(db: Session) -> BusinessCalendar:
    calendar = BusinessCalendar(name="Календарь для теста", timezone="Europe/Moscow")
    db.add(calendar)
    db.commit()
    for weekday in range(5):
        db.add(
            BusinessCalendarWindow(
                calendar_id=calendar.id, weekday=weekday, start_time=time(9, 0), end_time=time(18, 0)
            )
        )
    db.commit()
    db.refresh(calendar)
    return calendar


def _window(weekday: int, start: str, end: str) -> CalendarWindowCreate:
    return CalendarWindowCreate(
        weekday=weekday, start_time=time.fromisoformat(start), end_time=time.fromisoformat(end)
    )


# --- рабочие часы -------------------------------------------------------


def test_working_hours_can_be_changed(db: Session, calendar: BusinessCalendar):
    """Раньше окна задавались только при создании календаря: сменить часы
    поддержки можно было только правкой в БД."""
    replace_calendar_windows(
        calendar_id=calendar.id,
        windows=[_window(w, "08:00", "20:00") for w in range(5)],
        db=db,
        _=None,
    )

    db.refresh(calendar)
    assert {w.start_time for w in calendar.windows} == {time(8, 0)}
    assert {w.end_time for w in calendar.windows} == {time(20, 0)}


def test_replacing_windows_removes_the_old_ones(db: Session, calendar: BusinessCalendar):
    """Окна заменяются набором целиком: перевод на четырёхдневку не должен
    оставить пятницу от прежней настройки."""
    replace_calendar_windows(
        calendar_id=calendar.id, windows=[_window(w, "09:00", "18:00") for w in range(4)], db=db, _=None
    )

    db.refresh(calendar)
    assert sorted(w.weekday for w in calendar.windows) == [0, 1, 2, 3]


def test_empty_set_makes_the_calendar_closed(db: Session, calendar: BusinessCalendar):
    replace_calendar_windows(calendar_id=calendar.id, windows=[], db=db, _=None)
    db.refresh(calendar)
    assert calendar.windows == []


def test_backwards_window_is_rejected(db: Session, calendar: BusinessCalendar):
    """Окно «с 18:00 до 09:00» молча дало бы нулевое рабочее время и сдвинуло
    все сроки — отказ понятнее."""
    with pytest.raises(HTTPException) as exc:
        replace_calendar_windows(calendar_id=calendar.id, windows=[_window(0, "18:00", "09:00")], db=db, _=None)
    assert exc.value.status_code == 400


def test_two_windows_on_one_weekday_are_rejected(db: Session, calendar: BusinessCalendar):
    """В БД на это стоит уникальный индекс — без проверки запрос падал бы
    пятисоткой вместо внятного отказа."""
    with pytest.raises(HTTPException) as exc:
        replace_calendar_windows(
            calendar_id=calendar.id,
            windows=[_window(0, "09:00", "13:00"), _window(0, "14:00", "18:00")],
            db=db,
            _=None,
        )
    assert exc.value.status_code == 400


# --- праздники ----------------------------------------------------------


def test_period_creates_every_day(db: Session):
    """Новогодние каникулы — восемь дней; заводить их по одному значит
    повторить одно действие восемь раз."""
    created = create_holidays(
        HolidayCreate(holiday_date=date(2030, 1, 1), until_date=date(2030, 1, 8), name="Новогодние каникулы"),
        db=db, _=None,
    )
    assert len(created) == 8
    assert {h.holiday_date for h in created} == {date(2030, 1, d) for d in range(1, 9)}


def test_single_day_without_period(db: Session):
    created = create_holidays(HolidayCreate(holiday_date=date(2030, 6, 12), name="День России"), db=db, _=None)
    assert len(created) == 1


def test_existing_days_inside_the_period_are_skipped(db: Session):
    """Добавление майских поверх одного уже заведённого дня — обычная
    ситуация, а не ошибка. Раньше повторная дата давала 500."""
    create_holidays(HolidayCreate(holiday_date=date(2030, 5, 1), name="Праздник весны"), db=db, _=None)

    created = create_holidays(
        HolidayCreate(holiday_date=date(2030, 5, 1), until_date=date(2030, 5, 5), name="Майские"), db=db, _=None
    )

    assert len(created) == 4
    assert db.query(Holiday).filter(Holiday.holiday_date == date(2030, 5, 1)).count() == 1


def test_backwards_period_is_rejected(db: Session):
    with pytest.raises(HTTPException) as exc:
        create_holidays(
            HolidayCreate(holiday_date=date(2030, 1, 8), until_date=date(2030, 1, 1), name="Задом наперёд"),
            db=db, _=None,
        )
    assert exc.value.status_code == 400


def test_absurdly_long_period_is_rejected(db: Session):
    """Опечатка в годе превратила бы период в сотни выходных дней, и SLA
    встал бы по всем клиентам."""
    with pytest.raises(HTTPException) as exc:
        create_holidays(
            HolidayCreate(holiday_date=date(2030, 1, 1), until_date=date(2031, 1, 1), name="Опечатка"),
            db=db, _=None,
        )
    assert exc.value.status_code == 400


def test_holiday_can_be_removed(db: Session):
    created = create_holidays(HolidayCreate(holiday_date=date(2030, 11, 4), name="День единства"), db=db, _=None)
    delete_holiday(holiday_id=created[0].id, db=db, _=None)
    assert db.query(Holiday).filter(Holiday.holiday_date == date(2030, 11, 4)).count() == 0


def test_holidays_actually_move_sla_deadlines(db: Session, calendar: BusinessCalendar):
    """Смысл справочника: праздник должен выкидывать день из расчёта срока."""
    from app.services.calendar_math import add_working_minutes, load_spec

    calendar.observes_holidays = True
    db.add(calendar)
    db.commit()

    spec = load_spec(db, calendar.id)
    start = __import__("datetime").datetime(2030, 3, 6, 17, 0, tzinfo=__import__("datetime").timezone.utc)
    without = add_working_minutes(spec, start, 120)

    create_holidays(HolidayCreate(holiday_date=date(2030, 3, 7), name="Проверочный праздник"), db=db, _=None)
    spec = load_spec(db, calendar.id)
    with_holiday = add_working_minutes(spec, start, 120)

    assert with_holiday > without
