from pydantic import BaseModel, ConfigDict

from app.core.enums import ImpactUrgencyLevel, Priority


class ImpactUrgencyRuleCreate(BaseModel):
    impact: ImpactUrgencyLevel
    urgency: ImpactUrgencyLevel
    priority: Priority


class ImpactUrgencyRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    impact: ImpactUrgencyLevel
    urgency: ImpactUrgencyLevel
    priority: Priority
