from sqlalchemy import Boolean, Enum as SAEnum, Integer, String
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
    to_status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, native_enum=False, length=30, validate_strings=True)
    )
    threshold_days: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
