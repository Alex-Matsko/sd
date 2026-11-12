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
    changes_status = not values.actions or any(action.type == 'change_status' for action in values.actions)
    if changes_status and values.to_status not in ALLOWED_TRANSITIONS.get(values.from_status, set()):
        raise HTTPException(status_code=422, detail="Выбранный переход между статусами недопустим")
    if values.trigger_type == AutomationTriggerType.RESOLVED_WITHOUT_REPLY and values.from_status != TicketStatus.RESOLVED:
        raise HTTPException(status_code=422, detail="Для автозакрытия исходным статусом должен быть «Решена»")
    from app.models.organization import Organization
    from app.models.category import Category
    from app.models.team import Team
    for name, model in [('organization_id', Organization), ('category_id', Category), ('team_id', Team), ('assigned_engineer_id', User)]:
        value = getattr(values.filters, name)
        if value and db.get(model, value) is None:
            raise HTTPException(status_code=422, detail="Объект фильтра не найден")
    for action in values.actions:
        if any(db.get(User, user_id) is None for user_id in action.user_ids):
            raise HTTPException(status_code=422, detail="Получатель не найден")
    if values.is_active and changes_status:
        query = db.query(AutomationRule).filter(AutomationRule.is_active.is_(True), AutomationRule.from_status == values.from_status)
        if rule_id is not None:
            query = query.filter(AutomationRule.id != rule_id)
        for conflict in query:
            if conflict.actions and not any(action['type'] == 'change_status' for action in conflict.actions):
                continue
            current, other = values.filters.model_dump(mode='json'), conflict.filters or {}
            disjoint = any(current.get(key) and other.get(key) and current[key] != other[key]
                           for key in ('organization_id', 'category_id', 'team_id', 'assigned_engineer_id'))
            disjoint |= any(current.get(key) and other.get(key) and not (set(current[key]) & set(other[key]))
                            for key in ('priorities', 'channels'))
            disjoint |= bool((current.get('unassigned') and other.get('assigned_engineer_id')) or
                             (other.get('unassigned') and current.get('assigned_engineer_id')))
            if not disjoint:
                raise HTTPException(status_code=409, detail=f"Для этих заявок уже включено правило смены статуса «{conflict.name}». Сначала отключите его или разделите фильтры.")


@router.post('/preview')
def preview_automation_rule(payload: AutomationRuleCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    from app.services.automation import preview_rule
    # Preview deliberately ignores activation conflicts and never flushes actions.
    values = payload.model_copy(update={'is_active': False})
    _validate_rule(db, values)
    return preview_rule(db, AutomationRule(**values.model_dump()))


@router.get('/{rule_id}/runs')
def list_runs(rule_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    from app.models.automation_rule import AutomationRun
    from app.models.ticket import Ticket
    from app.models.channel_job import ChannelJob
    rows = db.query(AutomationRun, Ticket).join(Ticket, Ticket.id == AutomationRun.ticket_id).filter(
        AutomationRun.rule_id == rule_id).order_by(AutomationRun.created_at.desc(), AutomationRun.id.desc()).limit(100).all()
    return [{'id': run.id, 'ticket_id': ticket.id, 'display_number': ticket.display_number, 'subject': ticket.subject,
             'state': run.state, 'error': run.error, 'attempts': run.attempts, 'created_at': run.created_at,
             'occurrence': run.occurrence, 'revision': run.revision,
             'delivery': [{'id': job.id, 'state': job.state, 'error': job.last_error}
                          for job in db.query(ChannelJob).filter(ChannelJob.message_id.in_(run.message_ids))]}
            for run, ticket in rows]


@router.post('/{rule_id}/runs/{run_id}/retry', status_code=204)
def retry_run(rule_id: int, run_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)):
    from datetime import datetime, timezone
    from app.models.automation_rule import AutomationRun
    rule = db.get(AutomationRule, rule_id)
    run = db.query(AutomationRun).filter_by(id=run_id, rule_id=rule_id).with_for_update().first()
    if rule is None or run is None:
        raise HTTPException(status_code=404, detail="Выполнение не найдено")
    if run.state != 'error' or run.revision != rule.revision or not rule.is_active:
        raise HTTPException(status_code=409, detail="Повтор доступен для ошибок текущего включённого правила")
    run.attempts, run.available_at = 0, datetime.now(timezone.utc)
    db.commit()


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
    before = AutomationRuleCreate.model_validate(rule, from_attributes=True).model_dump()
    changed = any(before[field] != value for field, value in values.model_dump().items() if field not in {"is_active", "name"})
    if changed:
        rule.revision += 1
    for field, value in values.model_dump().items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule
