from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.enums import Channel, MessageDirection


class MessageCreate(BaseModel):
    request_id: UUID | None = None
    direction: MessageDirection
    body: str
    channel: Channel | None = None
    reply_to_message_id: int | None = None


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size_bytes: int
    mime_type: str | None
    created_at: datetime


class DeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    state: str
    attempts: int
    last_error: str | None
    available_at: datetime
    completed_at: datetime | None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    direction: MessageDirection
    channel: Channel
    author_user_id: int | None
    author_contact_id: int | None
    body: str
    reply_to_message_id: int | None
    created_at: datetime
    attachments: list[AttachmentRead] = []
    delivery: DeliveryRead | None = None
