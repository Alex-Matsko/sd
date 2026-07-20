from sqlalchemy.orm import Session

from app.core.enums import RoutingRuleType
from app.models.category import Category
from app.models.routing import RoutingRule


def resolve_assignment(db: Session, organization_id: int, category_id: int | None) -> tuple[int | None, int | None]:
    """Auto-assignment (section 4.4). Rules are evaluated in ascending `order`;
    the first match wins. Returns (team_id, engineer_id) - at most one is set.
    (None, None) means no rule matched: the ticket falls back to the general
    dispatcher queue."""
    rules = db.query(RoutingRule).filter(RoutingRule.is_active.is_(True)).order_by(RoutingRule.order).all()

    candidate_category_ids: set[int] = set()
    if category_id is not None:
        candidate_category_ids.add(category_id)
        category = db.get(Category, category_id)
        if category is not None and category.parent_id is not None:
            candidate_category_ids.add(category.parent_id)

    for rule in rules:
        if rule.rule_type == RoutingRuleType.ORGANIZATION_TO_ENGINEER:
            if rule.organization_id == organization_id:
                return None, rule.target_engineer_id
        elif rule.rule_type == RoutingRuleType.CATEGORY_TO_TEAM:
            if rule.category_id in candidate_category_ids:
                return rule.target_team_id, None

    return None, None
