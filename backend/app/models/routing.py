from sqlalchemy import Boolean, Enum as SAEnum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import RoutingRuleType
from app.models.base import Base, TimestampMixin


class RoutingRule(Base, TimestampMixin):
    """Auto-assignment rule (section 4.4). Rules are evaluated in ascending
    `order`; the first match wins. For rule_type=organization_to_engineer,
    `organization_id` and `target_engineer_id` are set. For
    rule_type=category_to_team, `category_id` and `target_team_id` are set."""

    __tablename__ = "routing_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    order: Mapped[int] = mapped_column(Integer)
    rule_type: Mapped[RoutingRuleType] = mapped_column(
        SAEnum(RoutingRuleType, native_enum=False, length=30, validate_strings=True)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))

    target_engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    target_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
