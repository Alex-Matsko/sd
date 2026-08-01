from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.core.enums import UserRole
from app.core.security import hash_password
from app.db import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _guard_admin_scope(actor: User, target_role: UserRole | None, target: User | None = None) -> None:
    """Only an administrator may create/modify an administrator or hand out the
    administrator role. Without this, `require_manager_or_above` let any
    manager promote themselves to admin, or reset the admin's password and
    take the account over - a straight privilege escalation (found in audit)."""
    if UserRole(actor.role) == UserRole.ADMIN:
        return
    if target is not None and UserRole(target.role) == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Изменять учётную запись администратора может только администратор",
        )
    if target_role is not None and UserRole(target_role) == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Назначить роль администратора может только администратор",
        )


@router.get("", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[User]:
    return db.query(User).order_by(User.full_name).all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate, db: Session = Depends(get_db), actor: User = Depends(require_manager_or_above)
) -> User:
    _guard_admin_scope(actor, payload.role)
    if db.query(User).filter(User.email == payload.email).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с таким email уже существует")
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        telegram_id=payload.telegram_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_manager_or_above),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    _guard_admin_scope(actor, payload.role, target=user)

    if user.id == actor.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя деактивировать собственную учётную запись"
        )

    data = payload.model_dump(exclude_unset=True, exclude={"password"})
    for field, value in data.items():
        setattr(user, field, value)
    if payload.password:
        user.password_hash = hash_password(payload.password)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user
