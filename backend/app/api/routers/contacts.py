from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_dispatcher_or_above
from app.db import get_db
from app.models.contact import Contact, ContactEmail, ContactPhone
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services import messenger_common

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactMergeRequest(BaseModel):
    into_contact_id: int


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


@router.post("/{contact_id}/merge", response_model=ContactRead)
def merge_contact(
    contact_id: int,
    payload: ContactMergeRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_dispatcher_or_above),
) -> Contact:
    """Manual counterpart to the bot's opt-in "связать телефон" flow (по
    запросу заказчика): a dispatcher who spots two Contact records that are
    really the same person - e.g. one created automatically per messenger
    channel before they were linked - merges `contact_id` into
    `into_contact_id`. Moves tickets/messages/channel state, then removes
    the now-empty duplicate; see messenger_common.merge_contacts."""
    if contact_id == payload.into_contact_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нельзя объединить контакт сам с собой")
    from_contact = db.get(Contact, contact_id)
    into_contact = db.get(Contact, payload.into_contact_id)
    if from_contact is None or into_contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    messenger_common.merge_contacts(db, from_contact=from_contact, into_contact=into_contact)
    db.refresh(into_contact)
    return into_contact


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
