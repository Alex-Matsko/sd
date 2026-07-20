from datetime import date, time

from sqlalchemy import Boolean, Date, ForeignKey, SmallInteger, String, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class BusinessCalendar(Base):
    """Working-hours calendar referenced by a Tariff. `is_24x7=True` calendars are
    always open (windows/holidays ignored). Others are open during the listed
    per-weekday windows and closed on registered holidays when
    `observes_holidays=True`."""

    __tablename__ = "business_calendars"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", server_default="Europe/Moscow")
    is_24x7: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    observes_holidays: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    windows: Mapped[list["BusinessCalendarWindow"]] = relationship(
        back_populates="calendar", cascade="all, delete-orphan"
    )


class BusinessCalendarWindow(Base):
    __tablename__ = "business_calendar_windows"
    __table_args__ = (UniqueConstraint("calendar_id", "weekday", name="uq_calendar_window_weekday"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("business_calendars.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday ... 6 = Sunday
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    calendar: Mapped["BusinessCalendar"] = relationship(back_populates="windows")


class Holiday(Base):
    """Shared RF holiday reference list, editable per year. Applied to every
    calendar with observes_holidays=True."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("holiday_date", name="uq_holidays_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(255))
