from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import AutomationTriggerType, TicketStatus


class AutomationRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    trigger_type: AutomationTriggerType
    from_status: TicketStatus
    to_status: TicketStatus
    threshold_days: int
    is_active: bool
    updated_at: datetime


class AutomationRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    trigger_type: AutomationTriggerType = AutomationTriggerType.STATUS_WITHOUT_REPLY
    from_status: TicketStatus
    to_status: TicketStatus
    threshold_days: int = Field(ge=1, le=3650)
    is_active: bool = False

    @model_validator(mode="after")
    def strip_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Укажите название правила")
        return self


class AutomationRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    trigger_type: AutomationTriggerType | None = None
    from_status: TicketStatus | None = None
    to_status: TicketStatus | None = None
    threshold_days: int | None = Field(default=None, ge=1, le=3650)
    is_active: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_nulls(cls, values):
        if isinstance(values, dict) and any(value is None for value in values.values()):
            raise ValueError("Поля правила не могут быть пустыми")
        return values
