import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.monitoring_alert import MonitoringAlert
from app.models.user import User
from app.services import monitoring

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
    resolved_at: str | None = None
    created_at: str


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

    if config.webhook_secret:
        provided = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or ""
        if not hmac.compare_digest(provided, config.webhook_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный секрет вебхука")

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
