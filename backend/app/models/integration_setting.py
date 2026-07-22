from sqlalchemy import Boolean, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Channel
from app.models.base import Base, TimestampMixin


class IntegrationSetting(Base, TimestampMixin):
    """Per-channel integration configuration (IMAP/SMTP now; Telegram bot token,
    MAX bridge, Plusofon API keys in later stages), editable from Настройки →
    Каналы instead of `.env` - one row per Channel, so a new integration only
    needs a new row + application-level config schema, not a migration.

    `config` holds non-secret fields as a flat JSON dict (host/port/username/
    poll interval/...). `secrets_encrypted` holds the same shape but only for
    sensitive keys (imap_password, smtp_password, ...), Fernet-encrypted
    (app.core.crypto) - the API never returns decrypted values, only which
    keys are currently set (schemas/integration_setting.py)."""

    __tablename__ = "integration_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[Channel] = mapped_column(
        SAEnum(Channel, native_enum=False, length=20, validate_strings=True), unique=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secrets_encrypted: Mapped[dict] = mapped_column(JSON, default=dict)
