import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_dispatcher_or_above
from app.core.enums import CallStatus, Channel, Priority, TicketType
from app.db import get_db
from app.models.call import Call
from app.models.contact import Contact
from app.models.user import User
from app.schemas.call import CallRead, CallTicketCreate
from app.schemas.ticket import TicketCreate, TicketRead
from app.services import sla as sla_service
from app.services import telephony
from app.services import tickets as tickets_service

logger = logging.getLogger("app.calls")

router = APIRouter(tags=["calls"])


@router.post("/webhooks/telephony", status_code=status.HTTP_202_ACCEPTED)
async def telephony_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Call events from Plusofon. Unauthenticated in the JWT sense (the PBX
    can't hold a user session), so it's protected by a shared secret from the
    channel settings, compared with `compare_digest` to avoid leaking the
    secret through response timing. Returns 202 on anything it can't parse
    rather than 4xx - a provider that retries on error would otherwise hammer
    the endpoint over a payload that will never parse; the event is logged
    instead."""
    config = telephony.load_config(db)
    if config is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Канал телефонии не настроен")

    if config.webhook_secret:
        provided = request.headers.get("X-Webhook-Secret") or request.query_params.get("secret") or ""
        if not hmac.compare_digest(provided, config.webhook_secret):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный секрет вебхука")

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Телефония: тело вебхука не является JSON")
        return {"accepted": False, "reason": "invalid_json"}

    try:
        call = telephony.ingest_call_event(db, payload, config)
    except ValueError as exc:
        logger.warning("Телефония: событие пропущено - %s", exc)
        return {"accepted": False, "reason": str(exc)}
    except Exception:
        logger.exception("Телефония: ошибка обработки события звонка")
        return {"accepted": False, "reason": "internal_error"}

    return {"accepted": True, "call_id": call.id, "ticket_id": call.ticket_id}


@router.get("/calls", response_model=list[CallRead])
def list_calls(
    response: Response,
    unhandled_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Call]:
    query = db.query(Call)
    if unhandled_only:
        # What the dispatcher panel polls: incoming calls nobody has taken
        # and that didn't already become a ticket.
        query = query.filter(Call.handled_at.is_(None), Call.ticket_id.is_(None))
    response.headers["X-Total-Count"] = str(query.count())
    return (
        query.order_by(Call.created_at.desc(), Call.id.desc())
        .limit(max(1, min(limit, 200)))
        .offset(max(0, offset))
        .all()
    )


def _get_call_or_404(db: Session, call_id: int) -> Call:
    call = db.get(Call, call_id)
    if call is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Звонок не найден")
    return call


@router.post("/calls/{call_id}/handled", response_model=CallRead)
def mark_call_handled(
    call_id: int, db: Session = Depends(get_db), _: User = Depends(require_dispatcher_or_above)
) -> Call:
    call = _get_call_or_404(db, call_id)
    if call.handled_at is None:
        call.handled_at = datetime.now(timezone.utc)
        db.add(call)
        db.commit()
        db.refresh(call)
    return call


@router.post("/calls/{call_id}/ticket", response_model=TicketRead)
def create_ticket_from_call(
    call_id: int,
    payload: CallTicketCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_dispatcher_or_above),
) -> TicketRead:
    """Section 2.4: «Создать заявку» с предзаполненным контактом."""
    call = _get_call_or_404(db, call_id)
    if call.ticket_id is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="По этому звонку заявка уже создана")

    contact_id = payload.contact_id or call.contact_id
    if contact_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Номер не опознан — выберите контакт вручную",
        )
    if db.get(Contact, contact_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Контакт не найден")

    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact_id,
            type=TicketType.INCIDENT,
            channel=Channel.PHONE,
            subject=payload.subject,
            manual_priority=Priority.P3,
            manual_priority_reason="Создано из карточки звонка - приоритет уточняется диспетчером",
        ),
        actor,
    )
    call.ticket_id = ticket.id
    call.contact_id = contact_id
    if call.handled_at is None:
        call.handled_at = datetime.now(timezone.utc)
    db.add(call)
    db.commit()

    view = TicketRead.model_validate(ticket)
    view.sla = sla_service.compute_view(db, ticket)
    return view


@router.get("/tickets/{ticket_id}/calls", response_model=list[CallRead])
def list_ticket_calls(
    ticket_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[Call]:
    """Call card shown on a phone-channel ticket (section 2.4: номер, время,
    длительность, ссылка на запись)."""
    return db.query(Call).filter(Call.ticket_id == ticket_id).order_by(Call.created_at).all()


@router.get("/calls/{call_id}", response_model=CallRead)
def get_call(call_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> Call:
    return _get_call_or_404(db, call_id)
