from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import get_db
from app.models.saved_filter import SavedFilter
from app.models.user import User

router = APIRouter(prefix="/saved-filters", tags=["saved-filters"])


class SavedFilterCreate(BaseModel):
    name: str
    criteria: dict = {}


class SavedFilterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    criteria: dict


@router.get("", response_model=list[SavedFilterRead])
def list_my_filters(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[SavedFilter]:
    return db.query(SavedFilter).filter(SavedFilter.user_id == user.id).order_by(SavedFilter.name).all()


@router.post("", response_model=SavedFilterRead, status_code=status.HTTP_201_CREATED)
def create_filter(
    payload: SavedFilterCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SavedFilter:
    """Saving under an existing name overwrites it - that's what "сохранить"
    means when the name already exists in your own list, and a 409 would just
    make the user delete and retry."""
    existing = (
        db.query(SavedFilter)
        .filter(SavedFilter.user_id == user.id, SavedFilter.name == payload.name.strip())
        .first()
    )
    if existing is not None:
        existing.criteria = payload.criteria
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    saved = SavedFilter(user_id=user.id, name=payload.name.strip(), criteria=payload.criteria)
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


@router.delete("/{filter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_filter(filter_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    saved = db.get(SavedFilter, filter_id)
    if saved is None:
        return
    if saved.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фильтр не найден")
    db.delete(saved)
    db.commit()
