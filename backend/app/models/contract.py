from datetime import date

from sqlalchemy import Date, Enum as SAEnum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ContractStatus
from app.models.base import Base, TimestampMixin


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("organization_id", "number", name="uq_contract_org_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    number: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    included_hours_per_month: Mapped[float] = mapped_column(Numeric(8, 2))
    overage_rate_per_hour: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[ContractStatus] = mapped_column(
        SAEnum(ContractStatus, native_enum=False, length=20, validate_strings=True),
        default=ContractStatus.ACTIVE,
        server_default=ContractStatus.ACTIVE.value,
    )

    organization: Mapped["Organization"] = relationship(back_populates="contracts")
    tariff: Mapped["Tariff"] = relationship()
