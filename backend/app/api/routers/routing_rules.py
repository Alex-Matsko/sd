from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.routing import RoutingRule
from app.models.user import User
from app.schemas.routing import RoutingRuleCreate, RoutingRuleRead, RoutingRuleUpdate

router = APIRouter(prefix="/routing-rules", tags=["routing-rules"])


@router.get("", response_model=list[RoutingRuleRead])
def list_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[RoutingRule]:
    return db.query(RoutingRule).order_by(RoutingRule.order).all()


@router.post("", response_model=RoutingRuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: RoutingRuleCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> RoutingRule:
    rule = RoutingRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RoutingRuleRead)
def update_rule(
    rule_id: int,
    payload: RoutingRuleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> RoutingRule:
    rule = db.get(RoutingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)) -> None:
    rule = db.get(RoutingRule, rule_id)
    if rule is not None:
        db.delete(rule)
        db.commit()
