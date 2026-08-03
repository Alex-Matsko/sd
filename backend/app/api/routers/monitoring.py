import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above, verify_webhook_secret
from app.core.enums import Channel
from app.db import get_db
from app.models.monitoring_alert import MonitoringAlert
from app.models.user import User
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.services import integration_settings, monitoring

logger = logging.getLogger("app.monitoring")

router = APIRouter(tags=["monitoring"])


class MonitoringAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    source: str
    severity: str | None
    host: str | None
    subject: str
    organization_id: int | None
    ticket_id: int | None
    resolved_at: datetime | None = None
    created_at: datetime


@router.post("/webhooks/monitoring", status_code=status.HTTP_202_ACCEPTED)
async def monitoring_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Alerts from Zabbix and similar. Same shape as the telephony webhook:
    shared-secret auth (the monitoring server has no user session), and a 202
    with a log line for anything unparseable rather than a 4xx that would
    make a retrying sender hammer the endpoint forever."""
    config = monitoring.load_config(db)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Интеграция с мониторингом не настроена"
        )

    verify_webhook_secret(request, config.webhook_secret)

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Мониторинг: тело вебхука не является JSON")
        return {"accepted": False, "reason": "invalid_json"}

    try:
        alert = monitoring.ingest_alert(db, payload, config)
    except ValueError as exc:
        logger.warning("Мониторинг: событие пропущено - %s", exc)
        return {"accepted": False, "reason": str(exc)}
    except Exception:
        logger.exception("Мониторинг: ошибка обработки события")
        return {"accepted": False, "reason": "internal_error"}

    return {"accepted": True, "alert_id": alert.id, "ticket_id": alert.ticket_id}


@router.get("/monitoring/alerts", response_model=list[MonitoringAlertRead])
def list_alerts(
    response: Response,
    unresolved_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MonitoringAlert]:
    query = db.query(MonitoringAlert)
    if unresolved_only:
        query = query.filter(MonitoringAlert.resolved_at.is_(None))
    response.headers["X-Total-Count"] = str(query.count())
    return (
        query.order_by(MonitoringAlert.created_at.desc(), MonitoringAlert.id.desc())
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
        .all()
    )


# --- настройки ------------------------------------------------------------
#
# Отдельный ресурс, а не карточка в списке каналов. Хранятся настройки в
# конфиге канала PORTAL (см. monitoring.load_config), но для интерфейса это
# деталь реализации: мониторинг — не клиентский канал, и «Портал» в списке
# каналов был бы фантомной записью, которую нельзя настроить.


class MonitoringSettingsRead(BaseModel):
    is_enabled: bool
    auto_resolve: bool
    default_contact_id: int | None
    field_map: dict[str, str]
    # Значение секрета не возвращается никогда — только признак, что он задан.
    webhook_secret_set: bool
    updated_at: datetime


class MonitoringSettingsUpdate(BaseModel):
    is_enabled: bool | None = None
    auto_resolve: bool | None = None
    default_contact_id: int | None = None
    field_map: dict[str, str] | None = None
    # Пропущено — не менять, null или "" — очистить, иначе — записать.
    # Различие «не передано» и «передано null» берётся из model_fields_set:
    # без него снять секрет было бы невозможно.
    webhook_secret: str | None = None


def _read_settings(setting) -> MonitoringSettingsRead:
    cfg = (setting.config or {}).get("monitoring") or {}
    return MonitoringSettingsRead(
        is_enabled=setting.is_enabled,
        auto_resolve=cfg.get("auto_resolve", True),
        default_contact_id=cfg.get("default_contact_id"),
        field_map={**monitoring.DEFAULT_FIELD_MAP, **(cfg.get("field_map") or {})},
        webhook_secret_set="monitoring_webhook_secret" in (setting.secrets_encrypted or {}),
        updated_at=setting.updated_at,
    )


@router.get("/settings/monitoring", response_model=MonitoringSettingsRead)
def get_monitoring_settings(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> MonitoringSettingsRead:
    return _read_settings(integration_settings.get_or_create(db, Channel.PORTAL))


@router.put("/settings/monitoring", response_model=MonitoringSettingsRead)
def update_monitoring_settings(
    payload: MonitoringSettingsUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> MonitoringSettingsRead:
    setting = integration_settings.get_or_create(db, Channel.PORTAL)
    current = (setting.config or {}).get("monitoring") or {}
    fields = payload.model_fields_set

    monitoring_config = dict(current)
    if "auto_resolve" in fields:
        monitoring_config["auto_resolve"] = payload.auto_resolve
    if "default_contact_id" in fields:
        monitoring_config["default_contact_id"] = payload.default_contact_id
    if "field_map" in fields:
        # Хранятся только отличия от значений по умолчанию: иначе изменение
        # умолчаний в коде не дошло бы до уже настроенных установок.
        overrides = {
            key: value
            for key, value in (payload.field_map or {}).items()
            if value and value != monitoring.DEFAULT_FIELD_MAP.get(key)
        }
        monitoring_config["field_map"] = overrides

    update = IntegrationSettingUpdate(
        is_enabled=payload.is_enabled,
        config={**(setting.config or {}), "monitoring": monitoring_config},
        secrets={"monitoring_webhook_secret": payload.webhook_secret} if "webhook_secret" in fields else None,
    )
    try:
        setting = integration_settings.upsert(db, Channel.PORTAL, update)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _read_settings(setting)
