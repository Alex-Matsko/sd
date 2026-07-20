from sqlalchemy import Enum as SAEnum
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ImpactUrgencyLevel, Priority
from app.models.base import Base


class ImpactUrgencyRule(Base):
    """The Impact x Urgency -> Priority matrix (section 4.1), global and editable.
    Ticket priority is computed by lookup here unless manually overridden."""

    __tablename__ = "impact_urgency_rules"
    __table_args__ = (UniqueConstraint("impact", "urgency", name="uq_impact_urgency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    impact: Mapped[ImpactUrgencyLevel] = mapped_column(
        SAEnum(ImpactUrgencyLevel, native_enum=False, length=10, validate_strings=True)
    )
    urgency: Mapped[ImpactUrgencyLevel] = mapped_column(
        SAEnum(ImpactUrgencyLevel, native_enum=False, length=10, validate_strings=True)
    )
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority, native_enum=False, length=2, validate_strings=True))
