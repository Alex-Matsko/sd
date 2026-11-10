from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import ValidationError
from fastapi.responses import FileResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.api.deps import get_current_user, require_dispatcher_or_above
from app.core.enums import OPEN_TICKET_STATUSES, Channel, Priority, TicketStatus, UserRole
from app.db import get_db
from app.models.audit import AuditLog
from app.models.channel_job import ChannelJob
from app.models.message import Attachment, Message
from app.models.ticket import Ticket
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.audit import AuditLogRead
from app.schemas.message import AttachmentRead, MessageCreate, MessageRead
from app.schemas.ticket import TicketClientChange, TicketCreate, TicketRead, TicketSlaView, TicketUpdate
from app.schemas.time_entry import TimeEntryCreate, TimeEntryRead, TimeEntryUpdate
from app.services import attachments as attachments_service
from app.services import audit as audit_service
from app.services.message_content import MessageContentError
from app.services import ticket_access
from app.services import messages as messages_service
from app.services import sla as sla_service
from app.services import time_entries as time_entries_service
from app.services import tickets as tickets_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _get_ticket_or_404(db: Session, ticket_id: int, actor: User) -> Ticket:
    """Единственная точка получения заявки по id во всём сотрудническом API.

    Проверка видимости стоит здесь, а не в каждом эндпоинте: так её нельзя
    забыть, добавляя новый маршрут. Недоступная заявка отдаётся как 404, а не
    403 — иначе по коду ответа перебирается, какие номера заявок существуют.
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or not ticket_access.can_see(db, actor, ticket):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return ticket


def _read_with_sla(db: Session, ticket: Ticket, cache: sla_service.SlaCache | None = None) -> TicketRead:
    view = TicketRead.model_validate(ticket)
    view.sla = TicketSlaView.model_validate(sla_service.compute_view(db, ticket, cache))
    return view


MAX_PAGE_SIZE = 200


def _search_filter(query, q: str):
    """Free-text search over the subject, the message thread, and the
    OH-<number> display form.

    Two things worth knowing. The display number is a Python property, not a
    column, so an "OH-1042" query is turned back into the numeric `number` it
    renders from - otherwise searching by the number people actually see
    would match nothing. And the thread is searched via EXISTS rather than a
    join: a ticket whose subject *and* three messages all match would
    otherwise come back four times."""
    conditions = [
        Ticket.subject.ilike(f"%{q}%"),
        db_exists_message_match(q),
    ]
    digits = q.strip().upper().removeprefix("OH-").lstrip("#")
    if digits.isdigit():
        conditions.append(Ticket.number == int(digits))
    return query.filter(or_(*conditions))


def db_exists_message_match(q: str):
    return (
        select(Message.id)
        .where(Message.ticket_id == Ticket.id, Message.body.ilike(f"%{q}%"))
        .exists()
    )


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
    open_only: bool = False,
    exclude_archived: bool = False,
    overdue: bool = False,
    sort: Literal["created_desc", "number_asc", "number_desc"] = "created_desc",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[TicketRead]:
    """Paged ticket queue. The full match count goes back in `X-Total-Count`
    so the client can render "1–50 из N" without a second request, and the
    response body stays a plain array (no envelope) - every existing consumer
    keeps working unchanged.

    Выдача ограничена тем, что сотруднику положено видеть (ТЗ р. 6): для
    диспетчера и выше это вся очередь, инженеру — свои, командные и ещё не
    распределённые заявки."""
    query = ticket_access.visible_tickets_query(db, actor)
    if exclude_archived:
        query = query.filter(Ticket.status.notin_([TicketStatus.CLOSED, TicketStatus.CANCELLED]))
    if open_only or overdue:
        query = query.filter(Ticket.status.in_(OPEN_TICKET_STATUSES))
    if overdue:
        query = query.filter(
            Ticket.sla_resolution_due_at < datetime.now(timezone.utc),
            Ticket.sla_paused_at.is_(None),
            Ticket.sla_resolution_met.isnot(True),
        )
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
    ordering = {"created_desc": (Ticket.created_at.desc(), Ticket.id.desc()),
                "number_asc": (Ticket.number.asc(), Ticket.id.asc()),
                "number_desc": (Ticket.number.desc(), Ticket.id.desc())}[sort]
    tickets = (
        query.order_by(*ordering)
        .limit(max(1, min(limit, MAX_PAGE_SIZE)))
        .offset(max(0, offset))
        .all()
    )
    cache = sla_service.SlaCache()
    return [_read_with_sla(db, t, cache) for t in tickets]


@router.get("/stats")
def get_ticket_stats(db: Session = Depends(get_db), actor: User = Depends(get_current_user), tz: str = "UTC") -> dict:
    """Whole-queue counters for the dashboard. Computed in SQL rather than by
    counting a fetched list: once the queue is paged, counting client-side
    would silently report only the current page's worth (section 8 - the
    dashboard's numbers have to reflect the whole queue, not a window).

    Считается по той же видимой области, что и очередь (ТЗ р. 6): иначе
    инженер видел бы на дашборде цифры по всей компании, а в списке под ними
    — только свои заявки, и счётчики читались бы как ошибка."""
    try:
        user_timezone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Неизвестный часовой пояс") from exc
    visible = ticket_access.visible_tickets_query(db, actor).subquery()
    scoped = db.query(Ticket).join(visible, visible.c.id == Ticket.id)

    by_status = {
        status_value: count
        for status_value, count in scoped.with_entities(Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.status)
        .all()
    }
    overdue = (
        scoped.with_entities(func.count(Ticket.id))
        .filter(
            Ticket.status.in_(OPEN_TICKET_STATUSES),
            Ticket.sla_resolution_due_at.isnot(None),
            Ticket.sla_paused_at.is_(None),
            Ticket.sla_resolution_met.isnot(True),
            Ticket.sla_resolution_due_at < datetime.now(timezone.utc),
        )
        .scalar()
    )
    # Section 8.3 wants "SLA-риски сегодня" - open tickets whose resolution
    # deadline falls before the end of today, i.e. what has to be dealt with
    # now, as distinct from what is already overdue.
    now = datetime.now(timezone.utc)
    local_today = now.astimezone(user_timezone).date()
    end_of_day = datetime.combine(local_today, time.max, tzinfo=user_timezone)
    at_risk_today = (
        scoped.with_entities(func.count(Ticket.id))
        .filter(
            Ticket.status.in_(OPEN_TICKET_STATUSES),
            Ticket.sla_resolution_due_at.isnot(None),
            Ticket.sla_paused_at.is_(None),
            Ticket.sla_resolution_met.isnot(True),
            Ticket.sla_resolution_due_at >= now,
            Ticket.sla_resolution_due_at <= end_of_day,
        )
        .scalar()
    )

    # Поток за неделю: создано и закрыто по дням. Одно «создано» ничего не
    # говорит - вопрос в том, разгребается очередь или копится, а это видно
    # только в паре с «закрыто» (р. 8.3).
    week_start = local_today - timedelta(days=6)
    week_start_at = datetime.combine(week_start, time.min, tzinfo=user_timezone)
    created_day = func.date(func.timezone(tz, Ticket.created_at))
    closed_day = func.date(func.timezone(tz, Ticket.closed_at))
    created_rows = (
        scoped.with_entities(created_day, func.count(Ticket.id))
        .filter(Ticket.created_at >= week_start_at)
        .group_by(created_day)
        .all()
    )
    closed_rows = (
        scoped.with_entities(closed_day, func.count(Ticket.id))
        .filter(Ticket.closed_at.isnot(None), Ticket.closed_at >= week_start_at)
        .group_by(closed_day)
        .all()
    )
    created_by_day = {str(day): count for day, count in created_rows}
    closed_by_day = {str(day): count for day, count in closed_rows}
    week_flow = [
        {
            "date": day.isoformat(),
            "created": created_by_day.get(day.isoformat(), 0),
            "closed": closed_by_day.get(day.isoformat(), 0),
        }
        for day in (week_start + timedelta(days=offset) for offset in range(7))
    ]

    # Загрузка инженеров — управленческий виджет: кто чем занят, показывается
    # тем, кто ведёт всю очередь. Инженеру чужая нагрузка не нужна, а по
    # урезанной области виджет всё равно показывал бы только его самого.
    workload_rows = (
        db.query(User.full_name, func.count(Ticket.id))
        .join(Ticket, Ticket.assigned_engineer_id == User.id)
        .filter(Ticket.status.in_(OPEN_TICKET_STATUSES))
        .group_by(User.id, User.full_name)
        .order_by(func.count(Ticket.id).desc())
        .limit(10)
        .all()
        if ticket_access.sees_full_queue(actor)
        else []
    )

    return {
        "by_status": {s.value: by_status.get(s, 0) for s in TicketStatus},
        "open_total": sum(by_status.get(s, 0) for s in OPEN_TICKET_STATUSES),
        "overdue": int(overdue or 0),
        "at_risk_today": int(at_risk_today or 0),
        "week_flow": week_flow,
        "workload": [{"engineer_name": name, "open_tickets": count} for name, count in workload_rows],
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
def get_ticket(ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)) -> TicketRead:
    return _read_with_sla(db, _get_ticket_or_404(db, ticket_id, actor))


@router.patch("/{ticket_id}", response_model=TicketRead)
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TicketRead:
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    try:
        return _read_with_sla(db, tickets_service.update_ticket(db, ticket, payload, actor))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{ticket_id}/client", response_model=TicketRead)
def change_ticket_client(
    ticket_id: int,
    payload: TicketClientChange,
    db: Session = Depends(get_db),
    actor: User = Depends(require_dispatcher_or_above),
) -> TicketRead:
    """Организация и контакт заявки — см. tickets_service.change_client."""
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    try:
        return _read_with_sla(db, tickets_service.change_client(db, ticket, payload, actor))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{ticket_id}/related", response_model=list[TicketRead])
def list_related_tickets(
    ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)
) -> list[TicketRead]:
    """Section 8.2 "связанные заявки". `parent_ticket_id` has been written
    since the "поднять старую" bot flow, but nothing ever displayed it - so a
    revived ticket's history was recorded and invisible. Returns the parent
    and any children, both directions in one list."""
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    # Связанная заявка может быть чужой: сама по себе связь не даёт права
    # её читать, поэтому список фильтруется той же видимостью.
    related = (
        ticket_access.visible_tickets_query(db, actor)
        .filter(Ticket.parent_ticket_id == ticket.id)
        .all()
    )
    if ticket.parent_ticket_id is not None:
        parent = db.get(Ticket, ticket.parent_ticket_id)
        if parent is not None and ticket_access.can_see(db, actor, parent):
            related.insert(0, parent)
    cache = sla_service.SlaCache()
    return [_read_with_sla(db, t, cache) for t in related]


@router.get("/{ticket_id}/messages", response_model=list[MessageRead])
def list_messages(ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)) -> list[Message]:
    _get_ticket_or_404(db, ticket_id, actor)
    return db.query(Message).filter(Message.ticket_id == ticket_id).order_by(Message.created_at, Message.id).all()


@router.post("/{ticket_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
def create_message(
    ticket_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Message:
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    try:
        return messages_service.add_message(db, ticket, payload, author_user=actor)
    except messages_service.RequestConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MessageContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{ticket_id}/messages/send", response_model=MessageRead, status_code=201)
async def send_message(
    ticket_id: int, payload: str = Form(...), files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db), actor: User = Depends(get_current_user),
):
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    try:
        message_payload = MessageCreate.model_validate_json(payload)
        uploads = await attachments_service.read_uploads(files)
        if not message_payload.body.strip() and not uploads:
            raise HTTPException(status_code=422, detail="Введите сообщение или приложите файл")
        return messages_service.add_message(db, ticket, message_payload, author_user=actor, attachments=uploads)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Некорректные поля сообщения")
    except messages_service.RequestConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except MessageContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except attachments_service.AttachmentTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc))


async def _send_typed_message(ticket_id, payload, files, db, actor, direction):
    try:
        parsed = MessageCreate.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Некорректные поля сообщения")
    if parsed.direction.value != direction:
        raise HTTPException(status_code=422, detail="Тип сообщения не соответствует выбранному действию")
    return await send_message(ticket_id, payload, files, db, actor)


@router.post("/{ticket_id}/notes/send", response_model=MessageRead, status_code=201)
async def send_internal_note(ticket_id: int, payload: str = Form(...), files: list[UploadFile] = File(default=[]),
                             db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return await _send_typed_message(ticket_id, payload, files, db, actor, "internal_note")


@router.post("/{ticket_id}/replies/send", response_model=MessageRead, status_code=201)
async def send_customer_reply(ticket_id: int, payload: str = Form(...), files: list[UploadFile] = File(default=[]),
                              db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    return await _send_typed_message(ticket_id, payload, files, db, actor, "outbound")


@router.post("/{ticket_id}/messages/{message_id}/delivery/retry")
def retry_message_delivery(ticket_id: int, message_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    from app.services import channel_queue
    _get_ticket_or_404(db, ticket_id, actor)
    job = db.query(ChannelJob).filter_by(message_id=message_id, ticket_id=ticket_id, kind="outbound").with_for_update(skip_locked=True).first()
    if job is None:
        if db.query(ChannelJob.id).filter_by(message_id=message_id, ticket_id=ticket_id, kind="outbound").first():
            raise HTTPException(status_code=409, detail="Сообщение сейчас отправляется")
        raise HTTPException(status_code=404, detail="Отправка не найдена")
    if job.state not in ("failed", "retry"):
        raise HTTPException(status_code=409, detail="Сообщение уже отправляется или завершено")
    audit_service.record(db, entity_type="channel_job", entity_id=job.id, action="retry", user_id=actor.id,
                         changes={"state": job.state})
    channel_queue.retry(db, job)
    return {"state": job.state}


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
    actor: User = Depends(get_current_user),
) -> Attachment:
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    message = db.get(Message, message_id)
    if message is None or message.ticket_id != ticket.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сообщение не найдено")

    job = db.query(ChannelJob).filter_by(message_id=message.id, kind="outbound").with_for_update().first()
    if job is not None and job.state != "pending":
        raise HTTPException(status_code=409, detail="Сообщение уже отправляется. Отправьте файл новым сообщением.")
    content = await file.read(settings.default_ticket_attachment_limit_mb * 1024 * 1024 + 1)
    try:
        attachment = attachments_service.store_attachment(message.id, file.filename or "", content, file.content_type)
    except attachments_service.AttachmentTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))

    db.add(attachment)
    db.flush()
    if job is not None:
        job.payload = {**job.payload, "attachment_ids": [*job.payload.get("attachment_ids", []), attachment.id]}
    db.commit()
    db.refresh(attachment)
    return attachment


@router.get("/{ticket_id}/attachments/{attachment_id}")
def download_attachment(
    ticket_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> FileResponse:
    """Serves a stored attachment back. Without this, files arriving over
    email/MAX/Telegram were written to disk and listed in the API but could
    never be opened by anyone (found in audit). The attachment is resolved
    through its message's ticket, so an id from another ticket 404s rather
    than leaking a file across tickets."""
    ticket = _get_ticket_or_404(db, ticket_id, actor)
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
    ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)
) -> list[AuditLog]:
    _get_ticket_or_404(db, ticket_id, actor)
    return audit_service.get_ticket_history(db, ticket_id)


@router.get("/{ticket_id}/time-entries", response_model=list[TimeEntryRead])
def list_time_entries(
    ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)
) -> list[TimeEntry]:
    _get_ticket_or_404(db, ticket_id, actor)
    return db.query(TimeEntry).filter(TimeEntry.ticket_id == ticket_id).order_by(TimeEntry.entry_date).all()


@router.post("/{ticket_id}/time-entries", response_model=TimeEntryRead, status_code=status.HTTP_201_CREATED)
def create_time_entry(
    ticket_id: int,
    payload: TimeEntryCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TimeEntry:
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    return time_entries_service.create_time_entry(db, ticket, payload, actor)


@router.get("/timer/active")
def get_my_timer(db: Session = Depends(get_db), actor: User = Depends(get_current_user)) -> dict:
    """The running timer belongs to the person, not the ticket, so this lives
    outside /{ticket_id} - the UI needs to know a timer is running even when
    the engineer is looking at a different ticket."""
    timer = time_entries_service.get_active_timer(db, actor)
    if timer is None:
        return {"running": False}
    ticket = db.get(Ticket, timer.ticket_id)
    return {
        "running": True,
        "ticket_id": timer.ticket_id,
        "display_number": ticket.display_number if ticket else None,
        "started_at": timer.started_at,
    }


@router.post("/{ticket_id}/timer/start")
def start_timer(
    ticket_id: int, db: Session = Depends(get_db), actor: User = Depends(get_current_user)
) -> dict:
    ticket = _get_ticket_or_404(db, ticket_id, actor)
    timer = time_entries_service.start_timer(db, ticket, actor)
    return {"running": True, "ticket_id": timer.ticket_id, "started_at": timer.started_at}


@router.post("/timer/stop", response_model=TimeEntryRead | None)
def stop_timer(db: Session = Depends(get_db), actor: User = Depends(get_current_user)) -> TimeEntry | None:
    """Returns the booked entry, or null when the timer ran for under a
    minute (a mis-click) and nothing was written."""
    return time_entries_service.stop_timer(db, actor)


@router.delete("/{ticket_id}/time-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_entry(
    ticket_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    """Удаление ошибочного списания.

    Раньше запись можно было только исправить, но не убрать: списание,
    заведённое не на ту заявку, оставалось в счёте клиенту навсегда. Удалять
    может автор записи или руководитель — чужое время инженер не трогает.
    Операция попадает в историю заявки: это изменение суммы, которая уйдёт
    клиенту, и оно должно быть прослеживаемым.
    """
    _get_ticket_or_404(db, ticket_id, actor)
    entry = db.get(TimeEntry, entry_id)
    if entry is None or entry.ticket_id != ticket_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись времени не найдена")

    if entry.engineer_id != actor.id and UserRole(actor.role) not in (UserRole.MANAGER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Удалить чужую запись времени может только руководитель"
        )

    time_entries_service.delete_time_entry(db, entry, actor)


@router.patch("/{ticket_id}/time-entries/{entry_id}", response_model=TimeEntryRead)
def update_time_entry(
    ticket_id: int,
    entry_id: int,
    payload: TimeEntryUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> TimeEntry:
    _get_ticket_or_404(db, ticket_id, actor)
    entry = db.get(TimeEntry, entry_id)
    if entry is None or entry.ticket_id != ticket_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись времени не найдена")
    return time_entries_service.update_time_entry(db, entry, payload, actor)
