from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.enums import OPEN_TICKET_STATUSES, Channel, Priority, TicketStatus
from app.db import get_db
from app.models.audit import AuditLog
from app.models.message import Attachment, Message
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.audit import AuditLogRead
from app.schemas.message import AttachmentRead, MessageCreate, MessageRead
from app.schemas.ticket import TicketCreate, TicketRead, TicketUpdate
from app.schemas.time_entry import TimeEntryCreate, TimeEntryRead, TimeEntryUpdate
from app.services import attachments as attachments_service
from app.services import audit as audit_service
from app.services import messages as messages_service
from app.services import sla as sla_service
from app.services import time_entries as time_entries_service
from app.services import tickets as tickets_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _get_ticket_or_404(db: Session, ticket_id: int) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return ticket


def _read_with_sla(db: Session, ticket: Ticket, cache: sla_service.SlaCache | None = None) -> TicketRead:
    view = TicketRead.model_validate(ticket)
    view.sla = sla_service.compute_view(db, ticket, cache)
    return view


MAX_PAGE_SIZE = 200


def _search_filter(query, q: str):
    """Free-text search over subject plus the OH-<number> display form. The
    display number is a Python property, not a column, so an "OH-1042" query
    is turned back into the numeric `number` it renders from - otherwise
    searching by the number people actually see would match nothing."""
    conditions = [Ticket.subject.ilike(f"%{q}%")]
    digits = q.strip().upper().removeprefix("OH-").lstrip("#")
    if digits.isdigit():
        conditions.append(Ticket.number == int(digits))
    return query.filter(or_(*conditions))


@router.get("", response_model=list[TicketRead])
def list_tickets(
    response: Response,
    status_filter: TicketStatus | None = None,
    organization_id: int | None = None,
    assigned_engineer_id: int | None = None,
    priority: Priority | None = None,
    channel: Channel | None = None,
    sla_risk: Literal["warning", "breached"] | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[TicketRead]:
    """Paged ticket queue. The full match count goes back in `X-Total-Count`
    so the client can render "1–50 из N" without a second request, and the
    response body stays a plain array (no envelope) - every existing consumer
    keeps working unchanged."""
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
    if q:
        query = _search_filter(query, q)
    # SLA risk relies on the worker's escalation stamps: "warning" = the 75%
    # notification fired and the outcome is still open, "breached" = a fixed
    # violation on either timer.
    if sla_risk == "breached":
        query = query.filter(or_(Ticket.sla_reaction_met.is_(False), Ticket.sla_resolution_met.is_(False)))
    elif sla_risk == "warning":
        query = query.filter(
            or_(
                and_(Ticket.sla_reaction_warned_at.isnot(None), Ticket.sla_reaction_met.is_(None)),
                and_(Ticket.sla_resolution_warned_at.isnot(None), Ticket.sla_resolution_met.is_(None)),
            )
        )
    response.headers["X-Total-Count"] = str(query.count())
    tickets = (
        query.order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(max(1, min(limit, MAX_PAGE_SIZE)))
        .offset(max(0, offset))
        .all()
    )
    cache = sla_service.SlaCache()
    return [_read_with_sla(db, t, cache) for t in tickets]


@router.get("/stats")
def get_ticket_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Whole-queue counters for the dashboard. Computed in SQL rather than by
    counting a fetched list: once the queue is paged, counting client-side
    would silently report only the current page's worth (section 8 - the
    dashboard's numbers have to reflect the whole queue, not a window)."""
    by_status = {
        status_value: count
        for status_value, count in db.query(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all()
    }
    overdue = (
        db.query(func.count(Ticket.id))
        .filter(
            Ticket.status.in_(OPEN_TICKET_STATUSES),
            Ticket.sla_resolution_due_at.isnot(None),
            Ticket.sla_resolution_due_at < datetime.now(timezone.utc),
        )
        .scalar()
    )
    return {
        "by_status": {s.value: by_status.get(s, 0) for s in TicketStatus},
        "open_total": sum(by_status.get(s, 0) for s in OPEN_TICKET_STATUSES),
        "overdue": int(overdue or 0),
    }


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)
) -> TicketRead:
    try:
        return _read_with_sla(db, tickets_service.create_ticket(db, payload, actor))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> TicketRead:
    return _read_with_sla(db, _get_ticket_or_404(db, ticket_id))


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TicketRead:
    ticket = _get_ticket_or_404(db, ticket_id)
    try:
        return _read_with_sla(db, tickets_service.update_ticket(db, ticket, payload, actor))
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
    try:
        attachment = attachments_service.store_attachment(message.id, file.filename or "", content, file.content_type)
    except attachments_service.AttachmentTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))

    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{ticket_id}/attachments/{attachment_id}")
def download_attachment(
    ticket_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> FileResponse:
    """Serves a stored attachment back. Without this, files arriving over
    email/MAX/Telegram were written to disk and listed in the API but could
    never be opened by anyone (found in audit). The attachment is resolved
    through its message's ticket, so an id from another ticket 404s rather
    than leaking a file across tickets."""
    ticket = _get_ticket_or_404(db, ticket_id)
    attachment = (
        db.query(Attachment)
        .join(Message, Message.id == Attachment.message_id)
        .filter(Attachment.id == attachment_id, Message.ticket_id == ticket.id)
        .first()
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Вложение не найдено")
    path = Path(attachment.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Файл вложения недоступен на диске")
    return FileResponse(
        path,
        filename=attachment.filename,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.get("/{ticket_id}/history", response_model=list[AuditLogRead])
def get_ticket_history(
    ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[AuditLog]:
    _get_ticket_or_404(db, ticket_id)
    return audit_service.get_ticket_history(db, ticket_id)


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
