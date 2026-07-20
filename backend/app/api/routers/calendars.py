from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.calendar import BusinessCalendar, BusinessCalendarWindow, Holiday
from app.models.user import User
from app.schemas.calendar import (
    BusinessCalendarCreate,
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


@router.get("/holidays", response_model=list[HolidayRead])
def list_holidays(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Holiday]:
    return db.query(Holiday).order_by(Holiday.holiday_date).all()


@router.post("/holidays", response_model=HolidayRead, status_code=status.HTTP_201_CREATED)
def create_holiday(
    payload: HolidayCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> Holiday:
    holiday = Holiday(**payload.model_dump())
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holiday(
    holiday_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> None:
    holiday = db.get(Holiday, holiday_id)
    if holiday is not None:
        db.delete(holiday)
        db.commit()
