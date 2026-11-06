from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.organization import Organization

from app.api.deps import get_current_user, require_dispatcher_or_above
from app.db import get_db
from app.models.contact import Contact, ContactEmail, ContactPhone
from app.models.user import User
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.services import messenger_common, portal

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactMergeRequest(BaseModel):
    into_contact_id: int


class PortalPasswordRequest(BaseModel):
    password: str = Field(min_length=8)


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
    if db.get(Organization, payload.organization_id) is None:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    emails = list(dict.fromkeys(email.strip().lower() for email in payload.emails if email.strip()))
    phones = list(dict.fromkeys(phone.strip() for phone in payload.phones if phone.strip()))
    if emails and db.query(ContactEmail).filter(ContactEmail.email.in_(emails)).first():
        raise HTTPException(status_code=409, detail="Контакт с таким email уже существует")
    if phones and db.query(ContactPhone).filter(ContactPhone.phone.in_(phones)).first():
        raise HTTPException(status_code=409, detail="Контакт с таким телефоном уже существует")
    for field in ("telegram_id", "max_id"):
        value = getattr(payload, field)
        if value and db.query(Contact).filter(getattr(Contact, field) == value).first():
            raise HTTPException(status_code=409, detail="Этот аккаунт мессенджера уже привязан к контакту")
    contact = Contact(
        organization_id=payload.organization_id,
        full_name=payload.full_name,
        position=payload.position,
        telegram_id=payload.telegram_id,
        max_id=payload.max_id,
        can_view_org_tickets=payload.can_view_org_tickets,
        is_confirmed=payload.is_confirmed,
    )
    try:
        db.add(contact)
        db.flush()
        for i, email in enumerate(emails):
            db.add(ContactEmail(contact_id=contact.id, email=email.lower(), is_primary=(i == 0)))
        for i, phone in enumerate(phones):
            db.add(ContactPhone(contact_id=contact.id, phone=phone, is_primary=(i == 0)))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Контакт с такими реквизитами уже существует") from exc
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


@router.post("/{contact_id}/portal-password", status_code=status.HTTP_204_NO_CONTENT)
def set_portal_password(
    contact_id: int,
    payload: PortalPasswordRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_dispatcher_or_above),
) -> None:
    """Gives a client access to the portal (section 7). A dispatcher sets the
    first password; afterwards the client can also log in by magic link, so
    this is a way in rather than the only one. The contact needs at least one
    email address - that address is the portal login."""
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    if not contact.emails:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У контакта нет email — он будет логином в личном кабинете",
        )
    portal.set_password(db, contact, payload.password)


@router.delete("/{contact_id}/portal-password", status_code=status.HTTP_204_NO_CONTENT)
def revoke_portal_access(
    contact_id: int, db: Session = Depends(get_db), _: User = Depends(require_dispatcher_or_above)
) -> None:
    """Отзывает доступ в личный кабинет.

    Нужно, когда сотрудник клиента уволился: отрезать его было нечем —
    пароль оставался рабочим, а magic-link выдавался по адресу почты,
    который никуда не делся. Снимается и пароль, и невыпользованные ссылки
    для входа: живая ссылка из письма — такой же ключ, как пароль.
    """
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")
    portal.revoke_access(db, contact)


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
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Контакт с такими реквизитами уже существует") from exc
    db.refresh(contact)
    return contact
