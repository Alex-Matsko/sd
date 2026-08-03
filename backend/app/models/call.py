from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import CallDirection, CallStatus
from app.models.base import Base, TimestampMixin


class Call(Base, TimestampMixin):
    """A telephony call event (section 2.4, Plusofon). Kept as its own entity
    rather than folded into Ticket: most calls never become a ticket (answered
    and handled on the spot), and a ticket created from a call still needs the
    call's own facts - number, timing, duration, recording - which have no
    place on the ticket itself."""

    __tablename__ = "calls"

    # Индекс на внешний ключ к tickets: без него удаление заявки
    # проверяет эту таблицу полным перебором (миграция c3e91a5d70f4).
    __table_args__ = (Index("ix_calls_ticket_id", "ticket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Provider's own call id - the same call arrives as several webhook events
    # (ringing -> answered -> completed), all carrying this id, so it's what
    # makes ingestion idempotent instead of creating a row per event.
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    direction: Mapped[CallDirection] = mapped_column(
        SAEnum(CallDirection, native_enum=False, length=20, validate_strings=True)
    )
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, native_enum=False, length=20, validate_strings=True)
    )
    from_number: Mapped[str] = mapped_column(String(32))
    to_number: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    recording_url: Mapped[str | None] = mapped_column(String(1000))

    # Resolved from the caller's number where possible (section 2, rule 4:
    # "автоидентификация клиента... по номеру телефона"); stays NULL for an
    # unrecognized number, which is what puts the call in the dispatcher's
    # "unknown" bucket rather than silently guessing an organization.
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    # Set when a ticket was raised from this call (automatically for a missed
    # call, or by the dispatcher pressing "Создать заявку").
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    # Dispatcher acknowledgement: an unhandled incoming call stays on the
    # dispatcher panel until someone takes it or raises a ticket from it.
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped["Contact"] = relationship()
    organization: Mapped["Organization"] = relationship()
    ticket: Mapped["Ticket"] = relationship()
