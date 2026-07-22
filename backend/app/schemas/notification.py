from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.enums import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int | None
    type: NotificationType
    title: str
    created_at: datetime
    read_at: datetime | None
