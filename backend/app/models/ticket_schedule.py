from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Priority, ScheduleCadence, TicketType
from app.models.base import Base, TimestampMixin


class TicketSchedule(Base, TimestampMixin):
    """Recurring planned work - scheduled maintenance, monthly checks
    (по запросу заказчика, вне исходного ТЗ).

    Not in the original spec, but standard for an MSP on a retainer: the
    contract usually promises regular preventive work, and without this it
    lives in someone's calendar and gets forgotten. A schedule produces an
    ordinary Ticket, so SLA, routing, billing and reporting all apply
    unchanged - this is a ticket *source*, not a parallel entity."""

    __tablename__ = "ticket_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    # Whose name the generated ticket is filed under - required, because a
    # ticket needs a contact to resolve organization, contract and tariff.
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    assigned_engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    type: Mapped[TicketType] = mapped_column(
        SAEnum(TicketType, native_enum=False, length=20, validate_strings=True), default=TicketType.SERVICE_REQUEST
    )
    priority: Mapped[Priority] = mapped_column(
        SAEnum(Priority, native_enum=False, length=2, validate_strings=True), default=Priority.P3
    )

    cadence: Mapped[ScheduleCadence] = mapped_column(
        SAEnum(ScheduleCadence, native_enum=False, length=20, validate_strings=True)
    )
    # For weekly: 0-6 (Mon-Sun). For monthly: day of month, clamped to the
    # month's length so "31st" still fires in February.
    day_of_week: Mapped[int | None] = mapped_column(Integer)
    day_of_month: Mapped[int | None] = mapped_column(Integer)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # The date the next ticket is due. Stored rather than derived so the
    # sweep is a cheap indexed comparison, and so an admin can shift a single
    # occurrence without rewriting the whole cadence.
    next_run_on: Mapped[date] = mapped_column(Date)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship()
    contact: Mapped["Contact"] = relationship()
