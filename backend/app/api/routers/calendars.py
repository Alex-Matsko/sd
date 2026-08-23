from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.calendar import BusinessCalendar, BusinessCalendarWindow, Holiday
from app.models.user import User
from app.schemas.calendar import (
    BusinessCalendarCreate,
    CalendarWindowCreate,
    BusinessCalendarRead,
    BusinessCalendarUpdate,
    HolidayCreate,
    HolidayRead,
)

router = APIRouter(tags=["calendars"])


@router.get("/calendars", response_model=list[BusinessCalendarRead])
def list_calendars(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[BusinessCalendar]:
    return db.query(BusinessCalendar).order_by(BusinessCalendar.name).all()


@router.post("/calendars", response_model=BusinessCalendarRead, status_code=status.HTTP_201_CREATED)
def create_calendar(
    payload: BusinessCalendarCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> BusinessCalendar:
    calendar = BusinessCalendar(
        name=payload.name,
        timezone=payload.timezone,
        is_24x7=payload.is_24x7,
        observes_holidays=payload.observes_holidays,
    )
    db.add(calendar)
    db.flush()
    for window in payload.windows:
        db.add(BusinessCalendarWindow(calendar_id=calendar.id, **window.model_dump()))
    db.commit()
    db.refresh(calendar)
    return calendar


@router.get("/calendars/{calendar_id}", response_model=BusinessCalendarRead)
def get_calendar(
    calendar_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> BusinessCalendar:
    calendar = db.get(BusinessCalendar, calendar_id)
    if calendar is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Календарь не найден")
    return calendar


@router.patch("/calendars/{calendar_id}", response_model=BusinessCalendarRead)
def update_calendar(
    calendar_id: int,
    payload: BusinessCalendarUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> BusinessCalendar:
    calendar = db.get(BusinessCalendar, calendar_id)
    if calendar is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Календарь не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(calendar, field, value)
    db.add(calendar)
    db.commit()
    db.refresh(calendar)
    return calendar


@router.put("/calendars/{calendar_id}/windows", response_model=BusinessCalendarRead)
def replace_calendar_windows(
    calendar_id: int,
    windows: list[CalendarWindowCreate],
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> BusinessCalendar:
    """Заменяет рабочие часы календаря целиком.

    Отдельным маршрутом, как и SLA-правила тарифа: окна — это набор, и
    частичное изменение («поменяй вторник») означало бы возню с их
    идентификаторами на клиенте. Раньше окна задавались только при
    создании календаря и потом не менялись вовсе — сменить часы поддержки
    можно было только правкой в БД.
    """
    calendar = db.get(BusinessCalendar, calendar_id)
    if calendar is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Календарь не найден")

    for window in windows:
        if window.start_time >= window.end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Начало рабочего окна должно быть раньше конца",
            )
    weekdays = [w.weekday for w in windows]
    if len(set(weekdays)) != len(weekdays):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="На один день недели можно задать только одно окно"
        )

    calendar.windows.clear()
    db.flush()
    for window in windows:
        calendar.windows.append(BusinessCalendarWindow(**window.model_dump()))
    db.add(calendar)
    db.commit()
    db.refresh(calendar)
    return calendar


@router.get("/holidays", response_model=list[HolidayRead])
def list_holidays(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Holiday]:
    return db.query(Holiday).order_by(Holiday.holiday_date).all()


@router.post("/holidays", response_model=list[HolidayRead], status_code=status.HTTP_201_CREATED)
def create_holidays(
    payload: HolidayCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> list[Holiday]:
    """Добавляет один день или период.

    Период — потому что российские праздники идут блоками: новогодние
    каникулы это восемь дней, и заводить их по одному значит повторить одно
    и то же действие восемь раз.

    Уже отмеченные дни внутри периода пропускаются, а не роняют запрос:
    добавление майских поверх одного уже заведённого дня — обычная
    ситуация, а не ошибка. Раньше повторная дата давала 500.
    """
    until = payload.until_date or payload.holiday_date
    if until < payload.holiday_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Конец периода раньше начала")
    if (until - payload.holiday_date).days > 31:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Период длиннее месяца — вероятно, ошибка")

    existing = {
        row[0]
        for row in db.query(Holiday.holiday_date).filter(
            Holiday.holiday_date >= payload.holiday_date, Holiday.holiday_date <= until
        )
    }
    created = []
    current = payload.holiday_date
    while current <= until:
        if current not in existing:
            holiday = Holiday(holiday_date=current, name=payload.name)
            db.add(holiday)
            created.append(holiday)
        current += timedelta(days=1)
    db.commit()
    for holiday in created:
        db.refresh(holiday)
    return created


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(
    holiday_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> None:
    holiday = db.get(Holiday, holiday_id)
    if holiday is not None:
        db.delete(holiday)
        db.commit()
