from datetime import datetime

from pydantic import BaseModel, ConfigDict

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


class AutomationRuleUpdate(BaseModel):
    threshold_days: int | None = None
    is_active: bool | None = None
