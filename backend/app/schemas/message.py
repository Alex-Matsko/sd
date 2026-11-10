from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Channel, MessageDirection


class TextBlock(BaseModel):
    type: Literal["text"]
    text: str = Field(max_length=30000)


class ImageUploadBlock(BaseModel):
    type: Literal["image"]
    file_index: int = Field(ge=0, le=9)


class ImageBlock(BaseModel):
    type: Literal["image"]
    attachment_id: int = Field(ge=1)


class MessageCreate(BaseModel):
    request_id: UUID | None = None
    direction: MessageDirection
    body: str = Field(max_length=300000)
    content_blocks: list[TextBlock | ImageUploadBlock] | None = Field(default=None, max_length=100)
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
    content_blocks: list[TextBlock | ImageBlock] | None = None
    reply_to_message_id: int | None
    created_at: datetime
    attachments: list[AttachmentRead] = []
    delivery: DeliveryRead | None = None
