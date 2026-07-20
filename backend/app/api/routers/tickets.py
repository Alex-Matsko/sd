import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.config import settings
from app.core.enums import Channel, Priority, TicketStatus
from app.db import get_db
from app.models.message import Attachment, Message
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.message import AttachmentRead, MessageCreate, MessageRead
from app.schemas.ticket import TicketCreate, TicketRead, TicketUpdate
from app.schemas.time_entry import TimeEntryCreate, TimeEntryRead, TimeEntryUpdate
from app.services import messages as messages_service
from app.services import time_entries as time_entries_service
from app.services import tickets as tickets_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _get_ticket_or_404(db: Session, ticket_id: int) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return ticket


@router.get("", response_model=list[TicketRead])
def list_tickets(
    status_filter: TicketStatus | None = None,
    organization_id: int | None = None,
    assigned_engineer_id: int | None = None,
    priority: Priority | None = None,
    channel: Channel | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Ticket]:
    query = db.query(Ticket)
    if status_filter is not None:
        query = query.filter(Ticket.status == status_filter)
    if organization_id is not None:
        query = query.filter(Ticket.organization_id == organization_id)
    if assigned_engineer_id is not None:
        query = query.filter(Ticket.assigned_engineer_id == assigned_engineer_id)
    if priority is not None:
        query = query.filter(Ticket.priority == priority)
    if channel is not None:
        query = query.filter(Ticket.channel == channel)
    return query.order_by(Ticket.created_at.desc()).all()


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)
) -> Ticket:
    try:
        return tickets_service.create_ticket(db, payload, actor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Ticket:
    return _get_ticket_or_404(db, ticket_id)


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Ticket:
    ticket = _get_ticket_or_404(db, ticket_id)
    try:
        return tickets_service.update_ticket(db, ticket, payload, actor)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{ticket_id}/messages", response_model=list[MessageRead])
def list_messages(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[Message]:
    _get_ticket_or_404(db, ticket_id)
    return db.query(Message).filter(Message.ticket_id == ticket_id).order_by(Message.created_at).all()


@router.post("/{ticket_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def create_message(
    ticket_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Message:
    ticket = _get_ticket_or_404(db, ticket_id)
    return messages_service.add_message(db, ticket, payload, author_user=actor)


@router.post(
    "/{ticket_id}/messages/{message_id}/attachments",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    ticket_id: int,
    message_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Attachment:
    ticket = _get_ticket_or_404(db, ticket_id)
    message = db.get(Message, message_id)
    if message is None or message.ticket_id != ticket.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сообщение не найдено")

    content = await file.read()
    limit_bytes = settings.default_ticket_attachment_limit_mb * 1024 * 1024
    if len(content) > limit_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл превышает лимит {settings.default_ticket_attachment_limit_mb} МБ",
        )

    today = date.today()
    directory = Path(settings.attachments_dir) / str(today.year) / f"{today.month:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}_{file.filename}"
    stored_path = directory / stored_name
    stored_path.write_bytes(content)

    attachment = Attachment(
        message_id=message.id,
        filename=file.filename or stored_name,
        stored_path=str(stored_path),
        size_bytes=len(content),
        mime_type=file.content_type,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{ticket_id}/time-entries", response_model=list[TimeEntryRead])
def list_time_entries(
    ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[TimeEntry]:
    _get_ticket_or_404(db, ticket_id)
    return db.query(TimeEntry).filter(TimeEntry.ticket_id == ticket_id).order_by(TimeEntry.entry_date).all()


@router.post("/{ticket_id}/time-entries", response_model=TimeEntryRead, status_code=status.HTTP_201_CREATED)
def create_time_entry(
    ticket_id: int,
    payload: TimeEntryCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TimeEntry:
    ticket = _get_ticket_or_404(db, ticket_id)
    return time_entries_service.create_time_entry(db, ticket, payload, actor)


@router.patch("/{ticket_id}/time-entries/{entry_id}", response_model=TimeEntryRead)
def update_time_entry(
    ticket_id: int,
    entry_id: int,
    payload: TimeEntryUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TimeEntry:
    _get_ticket_or_404(db, ticket_id)
    entry = db.get(TimeEntry, entry_id)
    if entry is None or entry.ticket_id != ticket_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись времени не найдена")
    return time_entries_service.update_time_entry(db, entry, payload, actor)
