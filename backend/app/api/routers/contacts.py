from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_dispatcher_or_above
from app.db import get_db
from app.models.contact import Contact, ContactEmail, ContactPhone
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactRead])
def list_contacts(
    organization_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Contact]:
    query = db.query(Contact)
    if organization_id is not None:
        query = query.filter(Contact.organization_id == organization_id)
    return query.order_by(Contact.full_name).all()


@router.post("", response_model=ContactRead, status_code=status.HTTP_201_CREATED)
def create_contact(
    payload: ContactCreate, db: Session = Depends(get_db), _: User = Depends(require_dispatcher_or_above)
) -> Contact:
    contact = Contact(
        organization_id=payload.organization_id,
        full_name=payload.full_name,
        position=payload.position,
        telegram_id=payload.telegram_id,
        max_id=payload.max_id,
        is_vip=payload.is_vip,
        can_view_org_tickets=payload.can_view_org_tickets,
        is_confirmed=payload.is_confirmed,
    )
    db.add(contact)
    db.flush()
    for i, email in enumerate(payload.emails):
        db.add(ContactEmail(contact_id=contact.id, email=email.lower(), is_primary=(i == 0)))
    for i, phone in enumerate(payload.phones):
        db.add(ContactPhone(contact_id=contact.id, phone=phone, is_primary=(i == 0)))
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/{contact_id}", response_model=ContactRead)
def get_contact(contact_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    return contact


@router.patch("/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_dispatcher_or_above),
) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact
