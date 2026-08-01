from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import CallDirection, CallStatus


class CallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    direction: CallDirection
    status: CallStatus
    from_number: str
    to_number: str | None
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    recording_url: str | None
    contact_id: int | None
    organization_id: int | None
    ticket_id: int | None
    handled_at: datetime | None
    created_at: datetime


class CallTicketCreate(BaseModel):
    """Dispatcher raising a ticket from a call card (section 2.4: кнопка
    «Создать заявку» с предзаполненным контактом)."""

    subject: str
    contact_id: int | None = None
