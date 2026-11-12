from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AutomationTriggerType, TicketStatus
from app.models.base import Base, TimestampMixin


class AutomationRule(Base, TimestampMixin):
    """Time-based status transitions, evaluated by the worker.

    Supported conditions have explicit evaluation code, keeping rule
    validation and execution consistent without arbitrary executable scripts.
    """

    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    trigger_type: Mapped[AutomationTriggerType] = mapped_column(
        SAEnum(AutomationTriggerType, native_enum=False, length=40, validate_strings=True)
    )
    from_status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, length=30, validate_strings=True)
    )
    to_status: Mapped[TicketStatus | None] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, length=30, validate_strings=True)
    )
    threshold_days: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    delay_hours: Mapped[int | None] = mapped_column(Integer)
    filters: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    actions: Mapped[list] = mapped_column(JSON, default=list, server_default='[]')
    repeat_hours: Mapped[int | None] = mapped_column(Integer)
    max_runs: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default='1')


class AutomationRun(Base):
    __tablename__ = 'automation_runs'
    __table_args__ = (UniqueConstraint('rule_id', 'ticket_id', 'revision', 'episode', 'occurrence', name='uq_automation_run'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey('automation_rules.id', ondelete='CASCADE'), index=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    episode: Mapped[str] = mapped_column(String(64))
    occurrence: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default='applied')
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text)
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
