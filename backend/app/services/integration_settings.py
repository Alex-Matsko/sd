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


# Секреты, которые внешняя система шлёт нам HTTP-заголовком. Заголовки
# декодируются как latin-1, поэтому секрет с кириллицей совпал бы при
# передаче в query-параметре и не совпал бы в заголовке — интеграция
# «то работает, то нет». Проще не дать завести такой секрет.
WEBHOOK_SECRET_KEYS = {"webhook_secret", "monitoring_webhook_secret"}


def _validate_secret(key: str, value: str) -> None:
    if key in WEBHOOK_SECRET_KEYS and not value.isascii():
        raise ValueError(
            "Секрет вебхука должен состоять из латинских букв, цифр и знаков препинания: "
            "внешняя система передаёт его HTTP-заголовком, где кириллица не проходит."
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
                _validate_secret(key, value)
                secrets[key] = crypto.encrypt(value)
        setting.secrets_encrypted = secrets
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def decrypt_secret(setting: IntegrationSetting, key: str) -> str | None:
    token = (setting.secrets_encrypted or {}).get(key)
    return crypto.decrypt(token) if token else None
