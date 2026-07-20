from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Priority
from app.models.base import Base


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(1000))
    business_calendar_id: Mapped[int] = mapped_column(ForeignKey("business_calendars.id"))

    sla_rules: Mapped[list["TariffSlaRule"]] = relationship(back_populates="tariff", cascade="all, delete-orphan")


class TariffSlaRule(Base):
    __tablename__ = "tariff_sla_rules"
    __table_args__ = (UniqueConstraint("tariff_id", "priority", name="uq_tariff_priority"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id", ondelete="CASCADE"))
    priority: Mapped[Priority] = mapped_column(SAEnum(Priority, native_enum=False, length=2, validate_strings=True))
    reaction_time_minutes: Mapped[int] = mapped_column(Integer)
    resolution_time_minutes: Mapped[int] = mapped_column(Integer)

    tariff: Mapped["Tariff"] = relationship(back_populates="sla_rules")
