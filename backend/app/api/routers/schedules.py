from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.core.enums import Priority, ScheduleCadence, TicketType
from app.db import get_db
from app.models.contact import Contact
from app.models.ticket_schedule import TicketSchedule
from app.models.user import User
from app.services import schedules as schedules_service

router = APIRouter(prefix="/ticket-schedules", tags=["ticket-schedules"])


class ScheduleCreate(BaseModel):
    is_active: bool = True
    name: str
    contact_id: int
    subject: str
    body: str | None = None
    cadence: ScheduleCadence
    type: TicketType = TicketType.SERVICE_REQUEST
    priority: Priority = Priority.P3
    category_id: int | None = None
    assigned_engineer_id: int | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    next_run_on: date | None = None


class ScheduleUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    body: str | None = None
    cadence: ScheduleCadence | None = None
    priority: Priority | None = None
    category_id: int | None = None
    assigned_engineer_id: int | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    is_active: bool | None = None
    next_run_on: date | None = None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    organization_id: int
    contact_id: int
    category_id: int | None
    assigned_engineer_id: int | None
    subject: str
    body: str | None
    type: TicketType
    priority: Priority
    cadence: ScheduleCadence
    day_of_week: int | None
    day_of_month: int | None
    is_active: bool
    next_run_on: date


@router.get("", response_model=list[ScheduleRead])
def list_schedules(
    organization_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[TicketSchedule]:
    query = db.query(TicketSchedule)
    if organization_id is not None:
        query = query.filter(TicketSchedule.organization_id == organization_id)
    return query.order_by(TicketSchedule.next_run_on).all()


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ScheduleCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> TicketSchedule:
    contact = db.get(Contact, payload.contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")

    data = payload.model_dump(exclude={"next_run_on"})
    schedule = TicketSchedule(**data, organization_id=contact.organization_id, next_run_on=date.today())
    # A schedule created today without an explicit start date should fire on
    # its next natural occurrence, not immediately on the next sweep.
    schedule.next_run_on = payload.next_run_on or schedules_service.compute_next_run(schedule, date.today())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.patch("/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> TicketSchedule:
    schedule = db.get(TicketSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Расписание не найдено")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> None:
    schedule = db.get(TicketSchedule, schedule_id)
    if schedule is not None:
        db.delete(schedule)
        db.commit()


@router.post("/{schedule_id}/run-now", response_model=ScheduleRead)
def run_now(
    schedule_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> TicketSchedule:
    """Creates this schedule's ticket immediately - for testing a new
    schedule without waiting for its date, and for the "нужно прямо сейчас"
    case. The next run is recalculated from today, as after a normal sweep."""
    schedule = db.get(TicketSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Расписание не найдено")
    schedule.next_run_on = date.today()
    db.add(schedule)
    db.commit()
    schedules_service.run_due_schedules(db)
    db.refresh(schedule)
    return schedule
