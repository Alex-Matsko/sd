import hmac
from collections.abc import Generator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.enums import UserRole
from app.core.security import decode_access_token
from app.db import get_db
from app.models.user import User
from app.services import settings_audit

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось подтвердить учётные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "access":
            raise credentials_error
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise credentials_error

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    # Автор запроса для автоматического аудита настроек. Кладётся в сессию,
    # а не в contextvar: синхронные зависимости FastAPI идут в отдельном
    # потоке, и значение из contextvar наружу не вернулось бы.
    settings_audit.set_actor(db, user.id)
    return user


def require_roles(*roles: UserRole):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if UserRole(user.role) not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для этого действия",
            )
        return user

    return dependency


require_dispatcher_or_above = require_roles(UserRole.DISPATCHER, UserRole.MANAGER, UserRole.ADMIN)
require_manager_or_above = require_roles(UserRole.MANAGER, UserRole.ADMIN)
require_admin = require_roles(UserRole.ADMIN)


def verify_webhook_secret(request: Request, expected: str | None) -> None:
    """Проверяет общий секрет вебхука (телефония, мониторинг).

    Секрет кодируется в байты перед сравнением: `hmac.compare_digest`
    на не-ASCII строках возбуждает TypeError, и вебхук отдавал 500 вместо
    401 — а секрет вводит человек, и написать его кириллицей никто не мешает.
    Сравнение остаётся постоянного времени, чтобы секрет не утекал через
    время ответа.
    """
    if not expected:
        return
    provided = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or ""
    if not hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный секрет вебхука")
