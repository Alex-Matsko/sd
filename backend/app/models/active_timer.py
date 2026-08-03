from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ActiveTimer(Base):
    """A running work timer (ТЗ 8.2 "таймер времени").

    One row per engineer, not per ticket: a person works on one thing at a
    time, and starting a timer on a second ticket stops the first. Without
    that rule two forgotten timers would both keep running and double-bill
    the same hour.

    Kept separate from TimeEntry because a running timer isn't a time entry
    yet - it has no duration until it stops, and a TimeEntry with a null
    duration would leak into billing and reports as a zero."""

    __tablename__ = "active_timers"

    # Индекс на внешний ключ к tickets: без него удаление заявки
    # проверяет эту таблицу полным перебором (миграция c3e91a5d70f4).
    __table_args__ = (Index("ix_active_timers_ticket_id", "ticket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
    ticket: Mapped["Ticket"] = relationship()
