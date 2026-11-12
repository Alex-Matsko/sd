from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    # `enabled` keeps already-open clients compatible during rollout.
    scope: Literal["all", "assigned", "off"] | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def one_setting(self):
        if (self.scope is None) == (self.enabled is None):
            raise ValueError("Передайте scope либо enabled")
        return self


class TelegramNotificationSettings(BaseModel):
    scope: Literal["all", "assigned", "off"]
