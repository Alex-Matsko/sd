from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.automation_rule import AutomationRule
from app.models.user import User
from app.schemas.automation_rule import AutomationRuleCreate, AutomationRuleRead, AutomationRuleUpdate

router = APIRouter(prefix="/automation-rules", tags=["automation-rules"])


@router.get("", response_model=list[AutomationRuleRead])
def list_automation_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[AutomationRule]:
    return db.query(AutomationRule).order_by(AutomationRule.id).all()



def _validate_rule(db, values, rule_id=None):
    from app.core.enums import AutomationTriggerType, TicketStatus
    from app.services.tickets import ALLOWED_TRANSITIONS
    if values.to_status not in ALLOWED_TRANSITIONS.get(values.from_status, set()):
        raise HTTPException(status_code=422, detail="Выбранный переход между статусами недопустим")
    if values.trigger_type == AutomationTriggerType.RESOLVED_WITHOUT_REPLY and values.from_status != TicketStatus.RESOLVED:
        raise HTTPException(status_code=422, detail="Для автозакрытия исходным статусом должен быть «Решена»")
    if values.is_active:
        query = db.query(AutomationRule).filter(AutomationRule.is_active.is_(True), AutomationRule.from_status == values.from_status)
        if rule_id is not None:
            query = query.filter(AutomationRule.id != rule_id)
        conflict = query.first()
        if conflict:
            raise HTTPException(status_code=409, detail=f"Для этого исходного статуса уже включено правило «{conflict.name}». Сначала отключите его.")


@router.post("", response_model=AutomationRuleRead, status_code=201)
def create_automation_rule(payload: AutomationRuleCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext("automation-rules"))))
    _validate_rule(db, payload)
    rule = AutomationRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=AutomationRuleRead)
def update_automation_rule(rule_id: int, payload: AutomationRuleUpdate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext("automation-rules"))))
    rule = db.get(AutomationRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    merged = {field: getattr(rule, field) for field in AutomationRuleCreate.model_fields}
    merged.update(payload.model_dump(exclude_unset=True))
    try:
        values = AutomationRuleCreate(**merged)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Проверьте название и параметры правила") from exc
    _validate_rule(db, values, rule.id)
    for field, value in values.model_dump().items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule
