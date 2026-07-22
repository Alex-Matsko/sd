from sqlalchemy.orm import Session

from app.core import crypto
from app.core.enums import Channel
from app.models.integration_setting import IntegrationSetting
from app.schemas.integration_setting import IntegrationSettingRead, IntegrationSettingUpdate


def get(db: Session, channel: Channel) -> IntegrationSetting | None:
    return db.query(IntegrationSetting).filter(IntegrationSetting.channel == channel).first()


def get_or_create(db: Session, channel: Channel) -> IntegrationSetting:
    setting = get(db, channel)
    if setting is None:
        setting = IntegrationSetting(channel=channel, is_enabled=False, config={}, secrets_encrypted={})
        db.add(setting)
        db.flush()
    return setting


def to_read(setting: IntegrationSetting) -> IntegrationSettingRead:
    return IntegrationSettingRead(
        channel=Channel(setting.channel),
        is_enabled=setting.is_enabled,
        config=setting.config or {},
        secret_keys_set=sorted((setting.secrets_encrypted or {}).keys()),
        updated_at=setting.updated_at,
    )


def upsert(db: Session, channel: Channel, payload: IntegrationSettingUpdate) -> IntegrationSetting:
    setting = get_or_create(db, channel)
    if payload.is_enabled is not None:
        setting.is_enabled = payload.is_enabled
    if payload.config is not None:
        setting.config = payload.config
    if payload.secrets is not None:
        secrets = dict(setting.secrets_encrypted or {})
        for key, value in payload.secrets.items():
            if not value:
                secrets.pop(key, None)
            else:
                secrets[key] = crypto.encrypt(value)
        setting.secrets_encrypted = secrets
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def decrypt_secret(setting: IntegrationSetting, key: str) -> str | None:
    token = (setting.secrets_encrypted or {}).get(key)
    return crypto.decrypt(token) if token else None
