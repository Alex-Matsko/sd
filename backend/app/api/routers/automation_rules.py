from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.automation_rule import AutomationRule
from app.models.user import User
from app.schemas.automation_rule import AutomationRuleRead, AutomationRuleUpdate

router = APIRouter(prefix="/automation-rules", tags=["automation-rules"])


@router.get("", response_model=list[AutomationRuleRead])
def list_automation_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[AutomationRule]:
    return db.query(AutomationRule).order_by(AutomationRule.id).all()


@router.patch("/{rule_id}", response_model=AutomationRuleRead)
def update_automation_rule(
    rule_id: int,
    payload: AutomationRuleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> AutomationRule:
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    if payload.threshold_days is not None and payload.threshold_days < 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Срок должен быть не менее 1 дня")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
