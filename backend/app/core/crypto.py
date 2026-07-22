"""Symmetric encryption for integration secrets at rest (IMAP/SMTP passwords,
future bot tokens/API keys in `integration_settings.secrets_encrypted`) - these
live in the DB instead of `.env` so they're editable from the settings UI
(section 8 ТЗ: "Настройки: ... каналы"), so they need the same protection a
plaintext .env value gets from filesystem permissions."""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    return Fernet(settings.settings_encryption_key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Не удалось расшифровать сохранённый секрет - проверьте SETTINGS_ENCRYPTION_KEY") from exc
