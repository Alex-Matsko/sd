from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class TimeEntry(Base, TimestampMixin):
    """A single logged work entry. `billed_package_minutes` +
    `billed_overage_minutes` always sum to `duration_minutes` and record how the
    entry was split across the contract's included-hours package vs. the overage
    rate at the moment it was logged (docs/decisions.md: proportional split)."""

    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"))
    engineer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(1000))
    is_billable: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    billed_package_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    billed_overage_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    ticket: Mapped["Ticket"] = relationship(back_populates="time_entries")
