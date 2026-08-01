from datetime import datetime

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class TelegramLinkCodeRead(BaseModel):
    code: str
    expires_at: datetime
