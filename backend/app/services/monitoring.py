"""Monitoring integration (Zabbix and similar) - по запросу заказчика, вне
исходного ТЗ.

An MSP finds out about most incidents from monitoring, not from the client,
so an alert has to become a ticket by itself. The webhook mirrors the
telephony one deliberately: shared-secret auth, a configurable field map,
and idempotency on the source system's own event id.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Channel, Priority, TicketStatus, TicketType
from app.models.contact import Contact
from app.models.monitoring_alert import MonitoringAlert
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate
from app.services import integration_settings
from app.services import tickets as tickets_service
from app.services.unknown_queue import get_or_create_unknown_organization

logger = logging.getLogger("app.monitoring")

DEFAULT_FIELD_MAP = {
    "external_id": "event_id",
    "subject": "subject",
    "body": "message",
    "severity": "severity",
    "host": "host",
    "organization": "organization",
    "status": "status",
}

# Zabbix sends PROBLEM/OK; other systems use firing/resolved. Anything not
# recognized as a recovery is treated as a problem - a missed recovery leaves
# a ticket open for a human to close, while a mistaken recovery would close a
# live incident silently.
RECOVERY_VALUES = {"ok", "resolved", "resolve", "recovery", "recovered", "closed", "0"}

SEVERITY_TO_PRIORITY = {
    "disaster": Priority.P1,
    "critical": Priority.P1,
    "high": Priority.P2,
    "average": Priority.P3,
    "warning": Priority.P3,
    "information": Priority.P4,
    "info": Priority.P4,
}


class MonitoringConfig:
    def __init__(self, webhook_secret: str | None, field_map: dict, auto_resolve: bool, default_contact_id: int | None):
        self.webhook_secret = webhook_secret
        self.field_map = field_map
        self.auto_resolve = auto_resolve
        self.default_contact_id = default_contact_id


def load_config(db: Session) -> MonitoringConfig | None:
    """Monitoring rides on the PORTAL channel's settings row - it isn't a
    client-facing channel of its own, and adding an enum member would mean a
    migration plus a phantom entry in the channels UI. The nesting under
    `monitoring` keeps it clearly separate from anything portal-related."""
    setting = integration_settings.get(db, Channel.PORTAL)
    if setting is None or not setting.is_enabled:
        return None
    cfg = (setting.config or {}).get("monitoring") or {}
    return MonitoringConfig(
        webhook_secret=integration_settings.decrypt_secret(setting, "monitoring_webhook_secret"),
        field_map={**DEFAULT_FIELD_MAP, **(cfg.get("field_map") or {})},
        auto_resolve=cfg.get("auto_resolve", True),
        default_contact_id=cfg.get("default_contact_id"),
    )


def _is_recovery(raw: Any) -> bool:
    return str(raw or "").strip().lower() in RECOVERY_VALUES


def _priority_for(severity: Any) -> Priority:
    return SEVERITY_TO_PRIORITY.get(str(severity or "").strip().lower(), Priority.P3)


def _resolve_contact(db: Session, organization_name: Any, config: MonitoringConfig) -> Contact:
    """Alerts name a host or an organization, never a person, so the ticket
    needs a contact to hang off. Preference order: a contact of the named
    organization, then the configured fallback contact, then a synthetic
    contact in "Неизвестные" - an alert must never be dropped for want of a
    person to attribute it to."""
    name = str(organization_name or "").strip()
    if name:
        organization = db.query(Organization).filter(Organization.name == name).first()
        if organization is not None:
            contact = db.query(Contact).filter(Contact.organization_id == organization.id).first()
            if contact is not None:
                return contact

    if config.default_contact_id:
        contact = db.get(Contact, config.default_contact_id)
        if contact is not None:
            return contact

    organization = get_or_create_unknown_organization(db)
    contact = db.query(Contact).filter(
        Contact.organization_id == organization.id, Contact.full_name == "Система мониторинга"
    ).first()
    if contact is None:
        contact = Contact(organization_id=organization.id, full_name="Система мониторинга", is_confirmed=False)
        db.add(contact)
        db.flush()
    return contact


def ingest_alert(db: Session, payload: dict, config: MonitoringConfig) -> MonitoringAlert:
    fields = config.field_map
    external_id = str(payload.get(fields["external_id"]) or "").strip()
    if not external_id:
        raise ValueError(f"В событии нет идентификатора (поле {fields['external_id']!r})")

    alert = db.query(MonitoringAlert).filter(MonitoringAlert.external_id == external_id).first()
    recovery = _is_recovery(payload.get(fields["status"]))

    if alert is None:
        if recovery:
            # A recovery for an alert we never saw: nothing to close, and
            # opening a ticket to say "it's fine now" would be noise.
            logger.info("Мониторинг: recovery по неизвестному событию %s - пропущено", external_id)
            alert = MonitoringAlert(
                external_id=external_id,
                subject=str(payload.get(fields["subject"]) or "Восстановление"),
                resolved_at=datetime.now(timezone.utc),
            )
            db.add(alert)
            db.commit()
            db.refresh(alert)
            return alert
        alert = MonitoringAlert(external_id=external_id, subject="")
        db.add(alert)

    alert.subject = str(payload.get(fields["subject"]) or alert.subject or f"Событие мониторинга {external_id}")[:500]
    alert.body = payload.get(fields["body"]) or alert.body
    alert.severity = payload.get(fields["severity"]) or alert.severity
    alert.host = payload.get(fields["host"]) or alert.host
    db.flush()

    if recovery:
        _handle_recovery(db, alert, config)
    elif alert.ticket_id is None:
        _open_ticket(db, alert, payload, config)

    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def _open_ticket(db: Session, alert: MonitoringAlert, payload: dict, config: MonitoringConfig) -> None:
    contact = _resolve_contact(db, payload.get(config.field_map["organization"]), config)
    host_prefix = f"[{alert.host}] " if alert.host else ""
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id,
            type=TicketType.INCIDENT,
            channel=Channel.PORTAL,
            subject=f"{host_prefix}{alert.subject}"[:500],
            manual_priority=_priority_for(alert.severity),
            manual_priority_reason=f"Автоматически из мониторинга (важность: {alert.severity or 'не указана'})",
            initial_message=alert.body,
        ),
        actor=None,
    )
    alert.ticket_id = ticket.id
    alert.organization_id = contact.organization_id
    alert.resolved_at = None


def _handle_recovery(db: Session, alert: MonitoringAlert, config: MonitoringConfig) -> None:
    alert.resolved_at = datetime.now(timezone.utc)
    if not config.auto_resolve or alert.ticket_id is None:
        return
    ticket = db.get(Ticket, alert.ticket_id)
    if ticket is None:
        return
    status = TicketStatus(ticket.status)
    if status in (TicketStatus.RESOLVED, TicketStatus.CLOSED, TicketStatus.CANCELLED):
        return
    try:
        # Same one-hop chain the client-initiated close uses: recovery means
        # the symptom is gone, not that a human reviewed it - so the ticket
        # goes to "Решена" and the normal auto-close rule takes it from there,
        # rather than being closed outright behind the engineer's back.
        if status not in (TicketStatus.IN_PROGRESS,):
            ticket = tickets_service.transition_status(db, ticket, TicketStatus.IN_PROGRESS, actor=None)
        tickets_service.transition_status(db, ticket, TicketStatus.RESOLVED, actor=None)
    except ValueError:
        logger.info("Мониторинг: заявку %s нельзя перевести в «Решена» из текущего статуса", ticket.display_number)
