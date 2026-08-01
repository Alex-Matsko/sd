from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_manager_or_above
from app.db import get_db
from app.models.response_template import ResponseTemplate
from app.models.user import User
from app.schemas.response_template import (
    ResponseTemplateCreate,
    ResponseTemplateRead,
    ResponseTemplateUpdate,
)

router = APIRouter(prefix="/response-templates", tags=["response-templates"])


@router.get("", response_model=list[ResponseTemplateRead])
def list_templates(
    category_id: int | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[ResponseTemplate]:
    """Every engineer reads templates; only managers edit them. Filtering by
    a ticket's category returns that category's templates *plus* the
    category-less ones, which are the general-purpose boilerplate."""
    query = db.query(ResponseTemplate)
    if not include_inactive:
        query = query.filter(ResponseTemplate.is_active.is_(True))
    if category_id is not None:
        query = query.filter(
            or_(ResponseTemplate.category_id == category_id, ResponseTemplate.category_id.is_(None))
        )
    return query.order_by(ResponseTemplate.name).all()


@router.post("", response_model=ResponseTemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: ResponseTemplateCreate, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> ResponseTemplate:
    template = ResponseTemplate(**payload.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=ResponseTemplateRead)
def update_template(
    template_id: int,
    payload: ResponseTemplateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_manager_or_above),
) -> ResponseTemplate:
    template = db.get(ResponseTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Шаблон не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int, db: Session = Depends(get_db), _: User = Depends(require_manager_or_above)
) -> None:
    template = db.get(ResponseTemplate, template_id)
    if template is not None:
        db.delete(template)
        db.commit()
