import secrets
import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.deps import check_login_allowed, get_current_user
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    revoke_refresh_tokens,
    verify_password,
)
from app.db import get_db
from app.services import login_guard
from app.models.auth import RefreshToken
from app.models.user import User
from app.schemas.auth import MaxNotificationSettings, TelegramNotificationSettings, PasswordChangeRequest, RefreshRequest, TelegramLinkCodeRead, TokenResponse
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

TELEGRAM_LINK_CODE_TTL_MINUTES = 15


def _issue_tokens(user: User, db: Session) -> TokenResponse:
    access_token = create_access_token(user.id, user.role)
    raw_refresh, refresh_hash, expires_at = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenResponse:
    client_ip = request.client.host if request.client else ""
    check_login_allowed("staff", form_data.username, client_ip)

    user = db.query(User).filter(User.email == form_data.username).first()
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    # Пароль проверяется даже для несуществующего адреса. Иначе ответ для
    # неизвестного пользователя приходит заметно быстрее — bcrypt не
    # выполняется, — и по времени ответа перебираются существующие учётки.
    password_hash = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    password_ok = verify_password(form_data.password, password_hash)

    if user is None or not user.is_active or not password_ok:
        login_guard.guard.register_failure("staff", form_data.username, client_ip)
        raise invalid

    login_guard.guard.register_success("staff", form_data.username, client_ip)
    return _issue_tokens(user, db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный refresh-токен")
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored is None or stored.revoked_at is not None:
        raise invalid
    if stored.expires_at < datetime.now(timezone.utc):
        raise invalid

    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise invalid

    stored.revoked_at = datetime.now(timezone.utc)
    db.add(stored)
    return _issue_tokens(user, db)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: Session = Depends(get_db)) -> None:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(timezone.utc)
        db.add(stored)
        db.commit()


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    payload: PasswordChangeRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    """Self-service password change. Previously only a manager/admin could set
    anyone's password via PATCH /users/{id}, which left an engineer with no way
    to rotate their own - including off the seeded default (found in audit).
    Revokes this user's refresh tokens so a stolen session can't outlive the
    password it was issued against."""
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Текущий пароль указан неверно")
    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    revoke_refresh_tokens(db, user)
    db.commit()


@router.post("/me/telegram-link-code", response_model=TelegramLinkCodeRead)
def request_telegram_link_code(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TelegramLinkCodeRead:
    """Self-service Telegram linking (section 8: "инженер привязывает свой
    TG в профиле") - the code is sent to the bot as "/link <code>"
    (services/telegram_channel.py), which sets telegram_id on this user
    without needing an admin to do it via user management."""
    code = secrets.token_hex(4).upper()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=TELEGRAM_LINK_CODE_TTL_MINUTES)
    user.telegram_link_code = code
    user.telegram_link_code_expires_at = expires_at
    db.add(user)
    db.commit()
    return TelegramLinkCodeRead(code=code, expires_at=expires_at)


@router.post("/me/telegram-unlink", response_model=UserRead)
def unlink_telegram(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    user.telegram_id = user.telegram_link_code = user.telegram_link_code_expires_at = None
    user.telegram_notification_scope = "off"
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/max-link-code", response_model=TelegramLinkCodeRead)
def request_max_link_code(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services import max_channel
    if max_channel.load_max_config(db) is None:
        raise HTTPException(status_code=409, detail="Канал MAX не настроен. Обратитесь к администратору.")
    user = db.query(User).filter_by(id=user.id).with_for_update().one()
    if user.max_id:
        raise HTTPException(status_code=409, detail="MAX уже привязан. Сначала отвяжите текущий аккаунт.")
    code = secrets.token_hex(6).upper()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    user.max_link_code_hash = hashlib.sha256(code.encode()).hexdigest()
    user.max_link_code_expires_at = expires_at
    db.commit()
    return TelegramLinkCodeRead(code=code, expires_at=expires_at)


@router.patch("/me/max-notifications", response_model=UserRead)
def update_max_notifications(payload: MaxNotificationSettings, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.audit import record
    user.max_notify_new_tickets = payload.enabled
    record(db, entity_type="user", entity_id=user.id, action="max_notifications_updated", user_id=user.id,
           changes={"enabled": payload.enabled})
    db.commit()
    return user


@router.post("/me/max-unlink", response_model=UserRead)
def unlink_max(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.audit import record
    user.max_id = user.max_chat_id = user.max_link_code_hash = user.max_link_code_expires_at = None
    user.max_notify_new_tickets = False
    record(db, entity_type="user", entity_id=user.id, action="max_unlinked", user_id=user.id)
    db.commit()
    return user


@router.patch("/me/telegram-notifications", response_model=UserRead)
def update_telegram_notifications(payload: TelegramNotificationSettings, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services import ticket_access
    if payload.scope == "all" and not ticket_access.sees_full_queue(user):
        raise HTTPException(status_code=403, detail="Уведомления обо всех заявках доступны только сотрудникам с доступом ко всей очереди")
    user.telegram_notification_scope = payload.scope
    db.commit()
    return user
