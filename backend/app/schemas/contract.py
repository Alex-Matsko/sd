from datetime import date

from pydantic import BaseModel, ConfigDict

from app.core.enums import ContractStatus


class ContractCreate(BaseModel):
    organization_id: int
    number: str
    start_date: date
    end_date: date | None = None
    tariff_id: int
    included_hours_per_month: float
    overage_rate_per_hour: float
    status: ContractStatus = ContractStatus.ACTIVE


class ContractUpdate(BaseModel):
    number: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    tariff_id: int | None = None
    included_hours_per_month: float | None = None
    overage_rate_per_hour: float | None = None
    status: ContractStatus | None = None


class ContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    number: str
    start_date: date
    end_date: date | None
    tariff_id: int
    included_hours_per_month: float
    overage_rate_per_hour: float
    status: ContractStatus
