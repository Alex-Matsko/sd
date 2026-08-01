"""Stage 6 telephony (section 2.4): call-event ingestion, caller
identification by number, and the automatic "Пропущенный звонок" ticket.
No provider is contacted - events are fed in exactly as the webhook would."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import CallDirection, CallStatus, Channel, TicketStatus
from app.models.call import Call
from app.models.contact import Contact, ContactPhone
from app.models.organization import Organization
from app.models.ticket import Ticket
from app.schemas.integration_setting import IntegrationSettingUpdate
from app.services import integration_settings, telephony


@pytest.fixture()
def phone_enabled(db: Session):
    integration_settings.upsert(
        db,
        Channel.PHONE,
        IntegrationSettingUpdate(
            is_enabled=True, config={"create_ticket_on_missed": True}, secrets={"webhook_secret": "s3cret"}
        ),
    )
    return telephony.load_config(db)


def _event(call_id="CALL-1", status="ringing", caller="+7 916 000-11-22", **extra) -> dict:
    return {"call_id": call_id, "direction": "in", "status": status, "caller_id": caller, **extra}


# --- parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ringing", CallStatus.RINGING),
        ("no_answer", CallStatus.MISSED),
        ("busy", CallStatus.MISSED),
        ("hangup", CallStatus.COMPLETED),
        ("answered", CallStatus.ANSWERED),
    ],
)
def test_status_aliases(raw, expected):
    assert telephony._parse_status(raw) == expected


def test_unknown_status_never_becomes_missed():
    """A missed status auto-creates a ticket, so an unrecognized provider
    value must not fall into that branch by accident."""
    assert telephony._parse_status("завершён-как-то-иначе") == CallStatus.COMPLETED


def test_timestamps_accept_iso_and_unix():
    assert telephony._parse_timestamp("2026-08-01T10:00:00Z") == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    assert telephony._parse_timestamp(1785484800).tzinfo is timezone.utc
    assert telephony._parse_timestamp(None) is None
    assert telephony._parse_timestamp("не время") is None


# --- ingestion -------------------------------------------------------


def test_event_without_call_id_is_rejected(db: Session, phone_enabled):
    with pytest.raises(ValueError):
        telephony.ingest_call_event(db, {"status": "ringing"}, phone_enabled)


def test_ringing_call_is_stored_without_a_ticket(db: Session, phone_enabled):
    call = telephony.ingest_call_event(db, _event(call_id="C-RING"), phone_enabled)
    assert call.status == CallStatus.RINGING
    assert call.direction == CallDirection.INBOUND
    assert call.ticket_id is None


def test_repeated_events_update_one_call_row(db: Session, phone_enabled):
    first = telephony.ingest_call_event(db, _event(call_id="C-SAME", start_time="2026-08-01T10:00:00Z"), phone_enabled)
    second = telephony.ingest_call_event(
        db, _event(call_id="C-SAME", status="hangup", duration=42, record_url="https://rec/1.mp3"), phone_enabled
    )
    assert first.id == second.id
    assert db.query(Call).filter(Call.external_id == "C-SAME").count() == 1
    assert second.duration_seconds == 42
    assert second.recording_url == "https://rec/1.mp3"
    # A later event that omits the start time must not wipe the earlier one.
    assert second.started_at is not None


def test_missed_call_creates_ticket_for_known_contact(db: Session, phone_enabled, contact: Contact):
    db.add(ContactPhone(contact_id=contact.id, phone="+7 916 000-11-22", is_primary=True))
    db.commit()

    call = telephony.ingest_call_event(db, _event(call_id="C-MISS", status="no_answer", caller="89160001122"), phone_enabled)

    assert call.contact_id == contact.id
    assert call.ticket_id is not None
    ticket = db.get(Ticket, call.ticket_id)
    assert ticket.channel == Channel.PHONE
    assert "Пропущенный звонок" in ticket.subject
    assert ticket.organization_id == contact.organization_id
    assert TicketStatus(ticket.status) in (TicketStatus.NEW, TicketStatus.ASSIGNED)


def test_missed_call_from_unknown_number_still_creates_ticket(db: Session, phone_enabled):
    call = telephony.ingest_call_event(
        db, _event(call_id="C-UNKNOWN", status="missed", caller="+7 999 777-66-55"), phone_enabled
    )
    assert call.ticket_id is not None
    contact = db.get(Contact, call.contact_id)
    assert contact.is_confirmed is False
    assert db.get(Organization, contact.organization_id).name == "Неизвестные"


def test_missed_call_does_not_create_a_second_ticket(db: Session, phone_enabled):
    telephony.ingest_call_event(db, _event(call_id="C-TWICE", status="no_answer"), phone_enabled)
    call = telephony.ingest_call_event(db, _event(call_id="C-TWICE", status="no_answer"), phone_enabled)
    tickets = db.query(Ticket).filter(Ticket.id == call.ticket_id).all()
    assert len(tickets) == 1


def test_missed_call_ticket_can_be_disabled(db: Session):
    integration_settings.upsert(
        db, Channel.PHONE, IntegrationSettingUpdate(is_enabled=True, config={"create_ticket_on_missed": False})
    )
    config = telephony.load_config(db)
    call = telephony.ingest_call_event(db, _event(call_id="C-NOTICKET", status="missed"), config)
    assert call.ticket_id is None


def test_answered_call_creates_no_ticket(db: Session, phone_enabled):
    call = telephony.ingest_call_event(db, _event(call_id="C-OK", status="answered"), phone_enabled)
    assert call.ticket_id is None


def test_caller_identification_matches_regardless_of_number_format(db: Session, phone_enabled, contact: Contact):
    db.add(ContactPhone(contact_id=contact.id, phone="8 (916) 111-22-33", is_primary=True))
    db.commit()
    assert telephony.identify_caller(db, "+79161112233").id == contact.id


def test_disabled_channel_yields_no_config(db: Session):
    integration_settings.upsert(db, Channel.PHONE, IntegrationSettingUpdate(is_enabled=False))
    assert telephony.load_config(db) is None


def test_field_map_is_overridable_per_installation(db: Session):
    """The provider's field names live in settings, not in code - so a account
    that reports the caller as `from` instead of `caller_id` is a form edit."""
    integration_settings.upsert(
        db,
        Channel.PHONE,
        IntegrationSettingUpdate(
            is_enabled=True, config={"field_map": {"external_id": "uuid", "from_number": "from"}}
        ),
    )
    config = telephony.load_config(db)
    call = telephony.ingest_call_event(db, {"uuid": "C-CUSTOM", "from": "+79990001122", "status": "ringing"}, config)
    assert call.external_id == "C-CUSTOM"
    assert call.from_number == "+79990001122"
