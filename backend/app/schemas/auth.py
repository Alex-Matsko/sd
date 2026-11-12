from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class TelegramLinkCodeRead(BaseModel):
    code: str
    expires_at: datetime


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class MaxNotificationSettings(BaseModel):
    enabled: bool


class TelegramNotificationSettings(BaseModel):
    scope: Literal["all", "assigned", "off"]
