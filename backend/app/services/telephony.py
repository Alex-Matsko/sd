"""Telephony channel (section 2.4, Plusofon): ingests call events, identifies
the caller by number, and raises a ticket for a missed call.

Plusofon's webhook payload shape is configurable rather than hard-coded - the
field names live in the channel settings (Настройки → Каналы → Телефония), so
adapting to the customer's actual account setup is a form edit, not a code
change. The reason is the MAX experience (docs/decisions.md): a shape
transcribed from public documentation without a live account to verify
against turned out wrong in three separate places. Here the mapping is at
least data, so a mismatch is fixable without a deploy.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import CallDirection, CallStatus, Channel, Priority, TicketType
from app.models.call import Call
from app.models.contact import Contact, ContactPhone
from app.models.ticket import Ticket
from app.schemas.ticket import TicketCreate
from app.services import integration_settings, messenger_common
from app.services import tickets as tickets_service
from app.services.unknown_queue import get_or_create_unknown_organization

logger = logging.getLogger("app.telephony")

# Defaults follow Plusofon's documented webhook fields; every one of them can
# be overridden per installation from the channel settings form.
DEFAULT_FIELD_MAP = {
    "external_id": "call_id",
    "direction": "direction",
    "status": "status",
    "from_number": "caller_id",
    "to_number": "called_did",
    "started_at": "start_time",
    "answered_at": "answer_time",
    "ended_at": "end_time",
    "duration_seconds": "duration",
    "recording_url": "record_url",
}

# Provider status vocabularies vary; anything unrecognized is kept as-is in
# the log and treated as "completed" so an unknown value can never silently
# create a phantom missed-call ticket.
STATUS_ALIASES = {
    "ringing": CallStatus.RINGING,
    "incoming": CallStatus.RINGING,
    "new": CallStatus.RINGING,
    "answered": CallStatus.ANSWERED,
    "answer": CallStatus.ANSWERED,
    "bridged": CallStatus.ANSWERED,
    "completed": CallStatus.COMPLETED,
    "hangup": CallStatus.COMPLETED,
    "end": CallStatus.COMPLETED,
    "missed": CallStatus.MISSED,
    "no_answer": CallStatus.MISSED,
    "noanswer": CallStatus.MISSED,
    "busy": CallStatus.MISSED,
    "cancel": CallStatus.MISSED,
    "failed": CallStatus.FAILED,
    "error": CallStatus.FAILED,
}


class TelephonyConfig:
    def __init__(self, webhook_secret: str | None, field_map: dict, create_ticket_on_missed: bool):
        self.webhook_secret = webhook_secret
        self.field_map = field_map
        self.create_ticket_on_missed = create_ticket_on_missed


def load_config(db: Session) -> TelephonyConfig | None:
    setting = integration_settings.get(db, Channel.PHONE)
    if setting is None or not setting.is_enabled:
        return None
    cfg = setting.config or {}
    return TelephonyConfig(
        webhook_secret=integration_settings.decrypt_secret(setting, "webhook_secret"),
        field_map={**DEFAULT_FIELD_MAP, **(cfg.get("field_map") or {})},
        create_ticket_on_missed=cfg.get("create_ticket_on_missed", True),
    )


def _parse_timestamp(value: Any) -> datetime | None:
    """Accepts both the ISO strings and the unix timestamps different
    Plusofon endpoints use for the same fields."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Телефония: не удалось разобрать время %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_status(raw: Any) -> CallStatus:
    key = str(raw or "").strip().lower()
    status = STATUS_ALIASES.get(key)
    if status is None:
        logger.warning("Телефония: неизвестный статус звонка %r - трактуем как завершённый", raw)
        return CallStatus.COMPLETED
    return status


def _parse_direction(raw: Any) -> CallDirection:
    return CallDirection.OUTBOUND if str(raw or "").strip().lower().startswith("out") else CallDirection.INBOUND


def identify_caller(db: Session, number: str) -> Contact | None:
    """Caller identification by phone number (section 2, rule 4). Reuses the
    messenger channels' normalization so the same person is recognized the
    same way whether they write or call - a number stored as +7 (916) …
    matches an incoming 8916… ."""
    return messenger_common.find_contact_by_phone(db, number)


def _create_missed_call_ticket(db: Session, call: Call) -> Ticket | None:
    """Section 2.4: "Если звонок пропущен — автоматически заявка «Пропущенный
    звонок» в очередь диспетчера". An unidentified number still produces a
    ticket, filed under the shared "Неизвестные" organization - a missed call
    from an unknown number is exactly the case a dispatcher must see."""
    contact = db.get(Contact, call.contact_id) if call.contact_id else None
    if contact is None:
        organization = get_or_create_unknown_organization(db)
        contact = Contact(
            organization_id=organization.id,
            full_name=f"Неизвестный номер {call.from_number}",
            is_confirmed=False,
        )
        db.add(contact)
        db.flush()
        db.add(ContactPhone(contact_id=contact.id, phone=call.from_number, is_primary=True))
        call.contact_id = contact.id
        call.organization_id = organization.id

    payload = TicketCreate(
        contact_id=contact.id,
        type=TicketType.INCIDENT,
        channel=Channel.PHONE,
        subject=f"Пропущенный звонок с {call.from_number}",
        manual_priority=Priority.P3,
        manual_priority_reason="Пропущенный звонок - приоритет уточняется диспетчером",
    )
    return tickets_service.create_ticket(db, payload, actor=None)


def ingest_call_event(db: Session, payload: dict, config: TelephonyConfig) -> Call:
    """Upserts one webhook event onto its call. Several events describe the
    same call, so this is keyed on the provider's call id and only fills in
    fields the event actually carries - a later "completed" event must not
    blank out the number an earlier "ringing" event supplied."""
    fields = config.field_map
    external_id = str(payload.get(fields["external_id"]) or "").strip()
    if not external_id:
        raise ValueError(f"В событии нет идентификатора звонка (поле {fields['external_id']!r})")

    call = db.query(Call).filter(Call.external_id == external_id).first()
    if call is None:
        call = Call(
            external_id=external_id,
            direction=_parse_direction(payload.get(fields["direction"])),
            status=CallStatus.RINGING,
            from_number=str(payload.get(fields["from_number"]) or "").strip() or "неизвестен",
        )
        db.add(call)

    call.status = _parse_status(payload.get(fields["status"]))
    for attr, parser in (
        ("to_number", lambda v: str(v).strip() if v else None),
        ("recording_url", lambda v: str(v).strip() if v else None),
        ("started_at", _parse_timestamp),
        ("answered_at", _parse_timestamp),
        ("ended_at", _parse_timestamp),
        ("duration_seconds", lambda v: int(v) if str(v).strip().isdigit() else None),
    ):
        raw = payload.get(fields[attr])
        parsed = parser(raw)
        if parsed is not None:
            setattr(call, attr, parsed)

    if call.contact_id is None and call.direction == CallDirection.INBOUND:
        contact = identify_caller(db, call.from_number)
        if contact is not None:
            call.contact_id = contact.id
            call.organization_id = contact.organization_id

    db.flush()

    if call.status == CallStatus.MISSED and call.ticket_id is None and config.create_ticket_on_missed:
        ticket = _create_missed_call_ticket(db, call)
        if ticket is not None:
            call.ticket_id = ticket.id

    db.add(call)
    db.commit()
    db.refresh(call)
    return call
