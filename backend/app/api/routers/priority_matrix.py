from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.priority import ImpactUrgencyRule
from app.models.user import User
from app.schemas.priority import ImpactUrgencyRuleCreate, ImpactUrgencyRuleRead

router = APIRouter(prefix="/priority-matrix", tags=["priority-matrix"])


@router.get("", response_model=list[ImpactUrgencyRuleRead])
def list_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[ImpactUrgencyRule]:
    return db.query(ImpactUrgencyRule).all()


@router.put("", response_model=list[ImpactUrgencyRuleRead])
def replace_matrix(
    rules: list[ImpactUrgencyRuleCreate],
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> list[ImpactUrgencyRule]:
    """Replaces the whole Impact x Urgency -> Priority matrix at once, so it's
    always fully defined (section 4.1)."""
    db.query(ImpactUrgencyRule).delete()
    created = []
    for rule in rules:
        row = ImpactUrgencyRule(**rule.model_dump())
        db.add(row)
        created.append(row)
    db.commit()
    for row in created:
        db.refresh(row)
    return created
