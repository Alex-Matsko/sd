import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def create_portal_access_token(contact_id: int) -> str:
    """Token for a client-portal session. `type: "portal"` is what keeps the
    two populations apart: `get_current_user` rejects anything that isn't
    `type: "access"`, so a client's token can never authenticate against the
    staff API even though both are signed with the same secret."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(contact_id),
        "type": "portal",
        "iat": now,
        "exp": now + timedelta(minutes=settings.portal_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token_to_return_to_client, sha256_hash_to_store, expires_at)."""
    raw = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    return raw, token_hash, expires_at


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def revoke_refresh_tokens(db, user) -> int:
    """Гасит все живые refresh-токены пользователя.

    Вынесено из auth-роутера: отзыв нужен в двух местах — при самостоятельной
    смене пароля и при сбросе администратором, — и во втором месте его просто
    забыли, из-за чего скомпрометированная сессия переживала смену пароля.
    """
    from datetime import datetime, timezone

    from app.models.auth import RefreshToken

    return (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .update({RefreshToken.revoked_at: datetime.now(timezone.utc)})
    )


# Хеш заведомо неподходящего пароля. Нужен, чтобы для несуществующего адреса
# проверка занимала столько же времени, сколько для существующего: без него
# ответ приходил заметно быстрее, и по времени ответа перебирались
# существующие учётные записи.
DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-login")
