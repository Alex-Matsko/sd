from datetime import datetime

from pydantic import BaseModel

from app.core.enums import Channel


class IntegrationSettingRead(BaseModel):
    channel: Channel
    is_enabled: bool
    config: dict
    # Which secret keys currently have a stored value - the value itself is
    # never returned. The settings form shows "•••• (задан)" for these and
    # leaves the field blank to mean "keep unchanged" on save.
    secret_keys_set: list[str]
    updated_at: datetime


class IntegrationSettingUpdate(BaseModel):
    is_enabled: bool | None = None
    config: dict | None = None
    # Per-key secret update: omitted key = leave unchanged, "" or null = clear,
    # non-empty = encrypt and store.
    secrets: dict[str, str | None] | None = None
