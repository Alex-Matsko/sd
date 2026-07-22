from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Identity, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Channel, ImpactUrgencyLevel, Priority, TicketStatus, TicketType
from app.models.base import Base, TimestampMixin


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Sequential ticket number, independent of `id`, backing the OH-<number>
    # display format (docs/decisions.md). A column-level IDENTITY rather than a
    # standalone Sequence object, so Alembic emits it inline with CREATE TABLE.
    number: Mapped[int] = mapped_column(Integer, Identity(start=1), unique=True)

    type: Mapped[TicketType] = mapped_column(SAEnum(TicketType, native_enum=False, length=20, validate_strings=True))
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, native_enum=False, length=20, validate_strings=True))
    subject: Mapped[str] = mapped_column(String(500))

    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contracts.id"))
    # Tariff resolved at creation time (from the contract, or the default fallback
    # tariff if the organization has no active contract - see docs/decisions.md).
    # Stored directly so the ticket's SLA stays stable even if the contract/tariff
    # changes later.
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    has_no_active_contract: Mapped[bool] = mapped_column(default=False, server_default="false")
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))

    impact: Mapped[ImpactUrgencyLevel | None] = mapped_column(
        SAEnum(ImpactUrgencyLevel, native_enum=False, length=10, validate_strings=True)
    )
    urgency: Mapped[ImpactUrgencyLevel | None] = mapped_column(
        SAEnum(ImpactUrgencyLevel, native_enum=False, length=10, validate_strings=True)
    )
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority, native_enum=False, length=2, validate_strings=True))
    priority_override_reason: Mapped[str | None] = mapped_column(String(1000))

    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, length=30, validate_strings=True),
        default=TicketStatus.NEW,
        server_default=TicketStatus.NEW.value,
    )
    assigned_engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    parent_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))

    # SLA bookkeeping (computed/maintained by the Stage 3 SLA engine; columns are
    # part of the Stage 1 schema so later stages don't need a migration for them).
    sla_reaction_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_resolution_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_paused_minutes_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Pause total in *working* minutes of the tariff calendar - the resolution
    # deadline is always created_at + working(resolution_minutes + this total).
    sla_paused_working_minutes_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # One-shot escalation stamps (75% warning / 100% breach, per timer) so the
    # worker sweep never notifies twice; reset when a priority change moves the
    # deadline (services/sla.py).
    sla_reaction_warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_reaction_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_resolution_warned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_resolution_escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_reaction_met: Mapped[bool | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_resolution_met: Mapped[bool | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # CSAT (section 2.1: "оценка после закрытия (1-5)"); full reporting is
    # Stage 9, but the messenger bots request/capture the rating now, so the
    # column exists ahead of that stage the same way the SLA ones did.
    csat_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csat_rating: Mapped[int | None] = mapped_column(Integer)
    csat_rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship()
    contact: Mapped["Contact"] = relationship()
    contract: Mapped["Contract"] = relationship()
    tariff: Mapped["Tariff"] = relationship()
    asset: Mapped["Asset"] = relationship()
    category: Mapped["Category"] = relationship()
    assigned_engineer: Mapped["User"] = relationship(foreign_keys="Ticket.assigned_engineer_id")
    team: Mapped["Team"] = relationship()
    parent_ticket: Mapped["Ticket"] = relationship(remote_side="Ticket.id")

    messages: Mapped[list["Message"]] = relationship(back_populates="ticket", order_by="Message.created_at")
    time_entries: Mapped[list["TimeEntry"]] = relationship(back_populates="ticket")

    @property
    def display_number(self) -> str:
        return f"OH-{self.number}"
