from sqlalchemy.orm import Session

from app.core.enums import ImpactUrgencyLevel, Priority
from app.models.priority import ImpactUrgencyRule


def compute_priority(db: Session, impact: ImpactUrgencyLevel, urgency: ImpactUrgencyLevel) -> Priority:
    """Looks up the Impact x Urgency -> Priority matrix (section 4.1)."""
    rule = (
        db.query(ImpactUrgencyRule)
        .filter(ImpactUrgencyRule.impact == impact, ImpactUrgencyRule.urgency == urgency)
        .first()
    )
    if rule is None:
        raise ValueError(f"В матрице приоритетов нет правила для impact={impact}, urgency={urgency}")
    return Priority(rule.priority)
