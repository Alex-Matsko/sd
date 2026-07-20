from pydantic import BaseModel, ConfigDict

from app.core.enums import RoutingRuleType


class RoutingRuleCreate(BaseModel):
    order: int
    rule_type: RoutingRuleType
    is_active: bool = True
    organization_id: int | None = None
    category_id: int | None = None
    target_engineer_id: int | None = None
    target_team_id: int | None = None


class RoutingRuleUpdate(BaseModel):
    order: int | None = None
    is_active: bool | None = None
    organization_id: int | None = None
    category_id: int | None = None
    target_engineer_id: int | None = None
    target_team_id: int | None = None


class RoutingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order: int
    rule_type: RoutingRuleType
    is_active: bool
    organization_id: int | None
    category_id: int | None
    target_engineer_id: int | None
    target_team_id: int | None
