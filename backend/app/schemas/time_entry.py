from datetime import date

from pydantic import BaseModel, ConfigDict


class TimeEntryCreate(BaseModel):
    entry_date: date
    duration_minutes: int
    comment: str | None = None
    is_billable: bool = True


class TimeEntryUpdate(BaseModel):
    entry_date: date | None = None
    duration_minutes: int | None = None
    comment: str | None = None
    is_billable: bool | None = None


class TimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    engineer_id: int
    entry_date: date
    duration_minutes: int
    comment: str | None
    is_billable: bool
    billed_package_minutes: int
    billed_overage_minutes: int
