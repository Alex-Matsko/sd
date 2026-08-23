from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import RoutingRuleType

# Поля, по которым можно ставить условие. Список закрытый: свободное
# выражение в админке пришлось бы валидировать и объяснять пользователю.
CONDITION_FIELDS = ("organization", "category", "channel", "priority", "type", "asset")


class RoutingCondition(BaseModel):
    field: Literal["organization", "category", "channel", "priority", "type", "asset"]
    # Одно значение или список: список читается как «любое из», чтобы
    # «канал — Telegram или MAX» было одним условием, а не двумя правилами.
    value: int | str | list[int | str]
    # «Кроме»: инвертирует именно это условие, не трогая остальные.
    negate: bool = False


class RoutingRuleCreate(BaseModel):
    order: int
    rule_type: RoutingRuleType
    name: str | None = None
    is_active: bool = True
    match: Literal["all", "any"] = "all"
    conditions: list[RoutingCondition] = Field(default_factory=list)
    organization_id: int | None = None
    category_id: int | None = None
    target_engineer_id: int | None = None
    target_team_id: int | None = None

    @field_validator("conditions")
    @classmethod
    def _no_duplicate_positive_fields(cls, conditions: list[RoutingCondition]) -> list[RoutingCondition]:
        """Два условия «организация = А» и «организация = Б» через «все
        сразу» не совпадут никогда — это молча неработающее правило.
        Условие «кроме» повторяться может: «кроме А и кроме Б» осмысленно."""
        seen = set()
        for condition in conditions:
            if condition.negate:
                continue
            if condition.field in seen:
                raise ValueError(
                    f"Поле «{condition.field}» указано дважды. Перечислите значения списком "
                    "или переключите правило на «любое из условий»"
                )
            seen.add(condition.field)
        return conditions


class RoutingRuleUpdate(BaseModel):
    order: int | None = None
    name: str | None = None
    is_active: bool | None = None
    match: Literal["all", "any"] | None = None
    conditions: list[RoutingCondition] | None = None
    organization_id: int | None = None
    category_id: int | None = None
    target_engineer_id: int | None = None
    target_team_id: int | None = None


class RoutingRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order: int
    name: str | None
    rule_type: RoutingRuleType
    is_active: bool
    match: str
    conditions: list[RoutingCondition]
    organization_id: int | None
    category_id: int | None
    target_engineer_id: int | None
    target_team_id: int | None
