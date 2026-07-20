from pydantic import BaseModel, ConfigDict

from app.core.enums import Priority


class TariffSlaRuleCreate(BaseModel):
    priority: Priority
    reaction_time_minutes: int
    resolution_time_minutes: int


class TariffSlaRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    priority: Priority
    reaction_time_minutes: int
    resolution_time_minutes: int


class TariffCreate(BaseModel):
    code: str
    name: str
    description: str | None = None
    business_calendar_id: int
    sla_rules: list[TariffSlaRuleCreate] = []


class TariffUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    business_calendar_id: int | None = None


class TariffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    business_calendar_id: int
    sla_rules: list[TariffSlaRuleRead] = []
