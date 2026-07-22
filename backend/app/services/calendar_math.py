"""Working-time arithmetic over a BusinessCalendar (section 4.3): SLA timers
count only the minutes inside the calendar's weekday windows, skipping
registered holidays. All public datetimes are UTC-aware; window clipping happens
in the calendar's own timezone."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, selectinload

from app.models.calendar import BusinessCalendar, Holiday

# Hard cap on the day-scan loop so a misconfigured calendar (e.g. every listed
# day is a holiday) fails loudly instead of spinning forever.
_MAX_SCAN_DAYS = 4000


@dataclass(frozen=True)
class CalendarSpec:
    tz: ZoneInfo
    is_24x7: bool
    windows: dict[int, list[tuple[time, time]]] = field(default_factory=dict)
    holidays: frozenset[date] = frozenset()

    @property
    def always_open(self) -> bool:
        # A non-24x7 calendar without a single window would make add_working
        # loop to the cap; degrade to 24x7 semantics instead.
        return self.is_24x7 or not any(self.windows.values())


def load_spec(db: Session, calendar_id: int) -> CalendarSpec:
    calendar = (
        db.query(BusinessCalendar)
        .options(selectinload(BusinessCalendar.windows))
        .filter(BusinessCalendar.id == calendar_id)
        .one()
    )
    windows: dict[int, list[tuple[time, time]]] = {}
    for w in calendar.windows:
        if w.start_time < w.end_time:
            windows.setdefault(w.weekday, []).append((w.start_time, w.end_time))
    for day_windows in windows.values():
        day_windows.sort()
    holidays: frozenset[date] = frozenset()
    if calendar.observes_holidays:
        holidays = frozenset(h.holiday_date for h in db.query(Holiday).all())
    return CalendarSpec(
        tz=ZoneInfo(calendar.timezone),
        is_24x7=calendar.is_24x7,
        windows=windows,
        holidays=holidays,
    )


def _day_windows(spec: CalendarSpec, day: date) -> list[tuple[time, time]]:
    if day in spec.holidays:
        return []
    return spec.windows.get(day.weekday(), [])


def add_working_minutes(spec: CalendarSpec, start: datetime, minutes: int) -> datetime:
    """The moment `minutes` of working time after `start` have elapsed."""
    if spec.always_open:
        return start + timedelta(minutes=minutes)

    remaining = timedelta(minutes=minutes)
    local_start = start.astimezone(spec.tz)
    day = local_start.date()
    for _ in range(_MAX_SCAN_DAYS):
        for window_start, window_end in _day_windows(spec, day):
            open_at = datetime.combine(day, window_start, tzinfo=spec.tz)
            close_at = datetime.combine(day, window_end, tzinfo=spec.tz)
            if close_at <= local_start:
                continue
            open_at = max(open_at, local_start)
            span = close_at - open_at
            if remaining <= span:
                return (open_at + remaining).astimezone(timezone.utc)
            remaining -= span
        day += timedelta(days=1)
    raise RuntimeError(f"Календарь без рабочих окон в ближайшие {_MAX_SCAN_DAYS} дней")


def working_timedelta_between(spec: CalendarSpec, start: datetime, end: datetime) -> timedelta:
    """Working time elapsed between two moments (0 when end <= start)."""
    if end <= start:
        return timedelta(0)
    if spec.always_open:
        return end - start

    local_start = start.astimezone(spec.tz)
    local_end = end.astimezone(spec.tz)
    total = timedelta(0)
    day = local_start.date()
    while day <= local_end.date():
        for window_start, window_end in _day_windows(spec, day):
            open_at = max(datetime.combine(day, window_start, tzinfo=spec.tz), local_start)
            close_at = min(datetime.combine(day, window_end, tzinfo=spec.tz), local_end)
            if open_at < close_at:
                total += close_at - open_at
        day += timedelta(days=1)
    return total


def working_minutes_between(spec: CalendarSpec, start: datetime, end: datetime) -> int:
    return int(working_timedelta_between(spec, start, end).total_seconds() // 60)
