from datetime import date, time

from pydantic import BaseModel, ConfigDict


class CalendarWindowCreate(BaseModel):
    weekday: int
    start_time: time
    end_time: time


class CalendarWindowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    weekday: int
    start_time: time
    end_time: time


class BusinessCalendarCreate(BaseModel):
    name: str
    timezone: str = "Europe/Moscow"
    is_24x7: bool = False
    observes_holidays: bool = True
    windows: list[CalendarWindowCreate] = []


class BusinessCalendarUpdate(BaseModel):
    name: str | None = None
    timezone: str | None = None
    is_24x7: bool | None = None
    observes_holidays: bool | None = None


class BusinessCalendarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    timezone: str
    is_24x7: bool
    observes_holidays: bool
    windows: list[CalendarWindowRead] = []


class HolidayCreate(BaseModel):
    holiday_date: date
    name: str
    # Российские праздники идут блоками (новогодние каникулы, майские), и
    # заводить их по одному — восемь одинаковых действий подряд. Пустое
    # поле означает один день.
    until_date: date | None = None


class HolidayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    holiday_date: date
    name: str
