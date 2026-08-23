from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.routing import RoutingRule
from app.models.team import Team
from app.models.user import User
from app.services import routing
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


class RoutingPreviewRequest(BaseModel):
    """Признаки воображаемой заявки: «а куда уйдёт вот такая?»"""

    organization_id: int
    category_id: int | None = None
    channel: str | None = None
    priority: str | None = None
    type: str | None = None
    asset_id: int | None = None


@router.post("/preview")
def preview_routing(
    payload: RoutingPreviewRequest, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> dict:
    """Показывает, какое правило сработает на заявке с такими признаками.

    С появлением условий правило перестало читаться с одного взгляда, а
    ошибка в маршрутизации обнаруживается не сразу: заявка просто уходит не
    туда. Проверка без создания заявки — единственный способ убедиться, что
    правило делает то, что задумано.
    """
    facts = routing.TicketFacts(
        organization_id=payload.organization_id,
        category_id=payload.category_id,
        channel=payload.channel,
        priority=payload.priority,
        ticket_type=payload.type,
        asset_id=payload.asset_id,
        category_path=routing._category_path(db, payload.category_id),
    )

    for rule in db.query(RoutingRule).filter(RoutingRule.is_active.is_(True)).order_by(RoutingRule.order):
        if not routing.rule_matches(rule, facts):
            continue
        engineer = db.get(User, rule.target_engineer_id) if rule.target_engineer_id else None
        team = db.get(Team, rule.target_team_id) if rule.target_team_id else None
        return {
            "matched": True,
            "rule_id": rule.id,
            "rule_name": rule.name,
            "target": engineer.full_name if engineer else (team.name if team else None),
            "target_kind": "engineer" if engineer else ("team" if team else None),
        }

    return {"matched": False, "rule_id": None, "rule_name": None, "target": None, "target_kind": None}


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)) -> None:
    rule = db.get(RoutingRule, rule_id)
    if rule is not None:
        db.delete(rule)
        db.commit()
