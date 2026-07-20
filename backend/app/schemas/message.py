from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import Channel, MessageDirection


class MessageCreate(BaseModel):
    direction: MessageDirection
    body: str
    channel: Channel | None = None


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size_bytes: int
    mime_type: str | None
    created_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    direction: MessageDirection
    channel: Channel
    author_user_id: int | None
    author_contact_id: int | None
    body: str
    created_at: datetime
    attachments: list[AttachmentRead] = []
