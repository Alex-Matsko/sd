from sqlalchemy import Boolean, Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AutomationTriggerType, TicketStatus
from app.models.base import Base, TimestampMixin


class AutomationRule(Base, TimestampMixin):
    """Status-automation rule, evaluated by the worker (services/automation.py)
    on the same cadence as the SLA sweep. Kept to one trigger type for now
    (auto-close, section 4.2) rather than a speculative generic condition/
    action DSL - `trigger_type` is the extension point for future rule kinds
    without a new migration, but each kind still needs matching evaluation
    code, same tradeoff as integration_settings.config."""

    __tablename__ = "automation_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    trigger_type: Mapped[AutomationTriggerType] = mapped_column(
        SAEnum(AutomationTriggerType, native_enum=False, length=40, validate_strings=True)
    )
    from_status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, length=30, validate_strings=True)
    )
    to_status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, length=30, validate_strings=True)
    )
    threshold_days: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
