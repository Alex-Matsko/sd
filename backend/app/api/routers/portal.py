"""Client portal API (section 7). Everything under /portal is authenticated
as a Contact, never as a staff User - see services/portal.py."""

import logging
from datetime import date, datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.enums import Channel, MessageDirection, Priority, TicketStatus, TicketType
from app.core.security import create_portal_access_token, decode_access_token
from app.db import get_db
from app.api.deps import check_login_allowed
from app.services import login_guard
from app.models.contact import Contact
from app.models.ticket import Ticket
from app.models.user import User
from app.schemas.message import MessageCreate
from app.schemas.portal import (
    PortalLoginRequest,
    PortalMagicLinkRequest,
    PortalMe,
    PortalMessageCreate,
    PortalMessageRead,
    PortalRatingRequest,
    PortalTicketCreate,
    PortalTicketDetail,
    PortalTicketRead,
    PortalTokenResponse,
    PortalUsage,
)
from app.schemas.ticket import TicketCreate
from app.services import billing, messages as messages_service, portal
from app.services import tickets as tickets_service
from app.services.contracts import resolve_contract_and_tariff

logger = logging.getLogger("app.portal")

router = APIRouter(prefix="/portal", tags=["portal"])
bearer = HTTPBearer(auto_error=False)


def get_current_contact(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> Contact:
    error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется вход в личный кабинет",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise error
    try:
        payload = decode_access_token(credentials.credentials)
        # A staff token must never open the portal and vice versa - the token
        # type is the boundary between the two populations.
        if payload.get("type") != "portal":
            raise error
        contact_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise error

    contact = db.get(Contact, contact_id)
    if contact is None:
        raise error
    return contact


# --- authentication -------------------------------------------------


@router.post("/auth/login", response_model=PortalTokenResponse)
def portal_login(
    request: Request, payload: PortalLoginRequest, db: Session = Depends(get_db)
) -> PortalTokenResponse:
    client_ip = request.client.host if request.client else ""
    check_login_allowed("portal", payload.email, client_ip)
    try:
        contact = portal.authenticate_with_password(db, payload.email, payload.password)
    except portal.PortalAuthError as exc:
        login_guard.guard.register_failure("portal", payload.email, client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    login_guard.guard.register_success("portal", payload.email, client_ip)
    return PortalTokenResponse(access_token=create_portal_access_token(contact.id))


@router.post("/auth/magic-link", status_code=status.HTTP_202_ACCEPTED)
def request_magic_link(
    request: Request, payload: PortalMagicLinkRequest, db: Session = Depends(get_db)
) -> dict:
    """Always answers the same way, known address or not - otherwise this
    endpoint tells an outsider who has a portal account at the client.

    Ограничение частоты нужно и здесь, хотя пароль тут не подбирают: без него
    эндпоинт превращается в средство завалить чужой ящик письмами и засорить
    базу одноразовыми токенами. Счётчик неудач не подходит — «неудач» тут не
    бывает, поэтому каждая выдача считается попыткой.
    """
    client_ip = request.client.host if request.client else ""
    check_login_allowed("magic-link", payload.email, client_ip)
    login_guard.guard.register_failure("magic-link", payload.email, client_ip)

    result = portal.issue_magic_link(db, payload.email)
    if result is not None:
        contact, link = result
        _send_magic_link(db, contact, link)
    return {"sent": True}


def _send_magic_link(db: Session, contact: Contact, link: str) -> None:
    """Best-effort delivery over the configured support mailbox. A failure is
    logged, never surfaced: the response must not differ based on whether
    delivery worked, and the client can simply ask for another link."""
    from app.services import email_channel

    recipient = next((e.email for e in contact.emails if e.is_primary), None) or (
        contact.emails[0].email if contact.emails else None
    )
    if recipient is None:
        return
    config = email_channel.load_email_config(db)
    if config is None:
        logger.warning("Портал: email-канал не настроен, magic-link не отправлен")
        return
    try:
        email_channel.send_plain_email(
            config,
            recipient,
            "Вход в личный кабинет «Открытые Горизонты»",
            f"Здравствуйте, {contact.full_name}!\n\n"
            f"Для входа в личный кабинет перейдите по ссылке:\n{link}\n\n"
            "Ссылка действует 30 минут и работает один раз. "
            "Если вы не запрашивали вход, просто проигнорируйте это письмо.",
        )
    except Exception:
        logger.exception("Портал: не удалось отправить magic-link")


@router.post("/auth/magic-link/consume", response_model=PortalTokenResponse)
def consume_magic_link(token: str, db: Session = Depends(get_db)) -> PortalTokenResponse:
    try:
        contact = portal.consume_magic_link(db, token)
    except portal.PortalAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PortalTokenResponse(access_token=create_portal_access_token(contact.id))


@router.get("/me", response_model=PortalMe)
def portal_me(contact: Contact = Depends(get_current_contact), db: Session = Depends(get_db)) -> PortalMe:
    from app.models.organization import Organization

    organization = db.get(Organization, contact.organization_id)
    return PortalMe(
        contact_id=contact.id,
        full_name=contact.full_name,
        organization=organization.name if organization else "—",
        can_view_org_tickets=contact.can_view_org_tickets,
    )


# --- tickets -------------------------------------------------------


def _engineer_names(db: Session, tickets: list[Ticket]) -> dict[int, str]:
    """Имена исполнителей одним запросом — иначе список заявок делал бы
    обращение к базе на каждую строку ради одного имени."""
    ids = {t.assigned_engineer_id for t in tickets if t.assigned_engineer_id}
    if not ids:
        return {}
    return {row[0]: row[1] for row in db.query(User.id, User.full_name).filter(User.id.in_(ids))}


def _to_read(ticket: Ticket, engineer_name: str | None = None) -> PortalTicketRead:
    return PortalTicketRead(
        id=ticket.id,
        display_number=ticket.display_number,
        subject=ticket.subject,
        status=TicketStatus(ticket.status),
        priority=Priority(ticket.priority),
        created_at=ticket.created_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
        csat_rating=ticket.csat_rating,
        assigned_engineer_name=engineer_name,
    )


@router.get("/tickets", response_model=list[PortalTicketRead])
def list_my_tickets(
    limit: int = 25,
    offset: int = 0,
    contact: Contact = Depends(get_current_contact),
    db: Session = Depends(get_db),
) -> list[PortalTicketRead]:
    tickets = (
        portal.visible_tickets_query(db, contact)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(max(1, min(limit, 100)))
        .offset(max(0, offset))
        .all()
    )
    names = _engineer_names(db, tickets)
    return [_to_read(t, names.get(t.assigned_engineer_id)) for t in tickets]


@router.post("/tickets", response_model=PortalTicketRead, status_code=status.HTTP_201_CREATED)
def create_my_ticket(
    payload: PortalTicketCreate,
    contact: Contact = Depends(get_current_contact),
    db: Session = Depends(get_db),
) -> PortalTicketRead:
    """A portal ticket is always filed against the logged-in contact - the
    client cannot choose whose name it goes under, so no contact_id is
    accepted from the request body."""
    ticket = tickets_service.create_ticket(
        db,
        TicketCreate(
            contact_id=contact.id,
            type=TicketType.INCIDENT,
            channel=Channel.PORTAL,
            subject=payload.subject,
            category_id=payload.category_id,
            manual_priority=Priority.P3,
            manual_priority_reason="Создано клиентом через портал - приоритет уточняется диспетчером",
            initial_message=payload.body,
        ),
        actor=None,
    )
    return _to_read(ticket, _engineer_names(db, [ticket]).get(ticket.assigned_engineer_id))


@router.get("/tickets/{ticket_id}", response_model=PortalTicketDetail)
def get_my_ticket(
    ticket_id: int, contact: Contact = Depends(get_current_contact), db: Session = Depends(get_db)
) -> PortalTicketDetail:
    ticket = portal.get_visible_ticket(db, contact, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    return PortalTicketDetail(
        **_to_read(ticket, _engineer_names(db, [ticket]).get(ticket.assigned_engineer_id)).model_dump(),
        messages=[
            PortalMessageRead(
                id=m.id,
                body=m.body,
                is_from_support=MessageDirection(m.direction) == MessageDirection.OUTBOUND,
                created_at=m.created_at,
            )
            for m in portal.visible_messages(db, ticket)
        ],
    )


@router.post("/tickets/{ticket_id}/messages", response_model=PortalMessageRead, status_code=status.HTTP_201_CREATED)
def reply_to_my_ticket(
    ticket_id: int,
    payload: PortalMessageCreate,
    contact: Contact = Depends(get_current_contact),
    db: Session = Depends(get_db),
) -> PortalMessageRead:
    ticket = portal.get_visible_ticket(db, contact, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")

    # Ответ в закрытую заявку раньше молча ложился в неё: она не
    # переоткрывалась, новая не заводилась, никого не уведомляли — сообщение
    # уходило в никуда. Email в этом случае заводит новую заявку, боты
    # предлагают «поднять старую»; портал вёл себя иначе, чем оба канала.
    # Теперь как в ботах: новая заявка, связанная с закрытой.
    if TicketStatus(ticket.status) in (TicketStatus.CLOSED, TicketStatus.CANCELLED):
        ticket = tickets_service.create_ticket(
            db,
            TicketCreate(
                contact_id=contact.id,
                type=TicketType(ticket.type),
                channel=Channel.PORTAL,
                subject=payload.body[:200] or f"Повторное обращение по {ticket.display_number}",
                manual_priority=Priority.P3,
                manual_priority_reason=f"Повторное обращение по закрытой заявке {ticket.display_number}",
                parent_ticket_id=ticket.id,
            ),
            actor=None,
        )

    message = messages_service.add_message(
        db,
        ticket,
        MessageCreate(direction=MessageDirection.INBOUND, body=payload.body, channel=Channel.PORTAL),
        author_contact=contact,
    )
    return PortalMessageRead(id=message.id, body=message.body, is_from_support=False, created_at=message.created_at)


@router.post("/tickets/{ticket_id}/rating", response_model=PortalTicketRead)
def rate_my_ticket(
    ticket_id: int,
    payload: PortalRatingRequest,
    contact: Contact = Depends(get_current_contact),
    db: Session = Depends(get_db),
) -> PortalTicketRead:
    """Section 7: "оценка закрытых заявок". Same one-shot rule as the bots'
    CSAT - a rating already given is never overwritten."""
    ticket = portal.get_visible_ticket(db, contact, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка не найдена")
    if TicketStatus(ticket.status) not in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Оценить можно только решённую заявку")
    if ticket.csat_rating is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Оценка уже получена ранее")

    ticket.csat_rating = payload.rating
    ticket.csat_rated_at = datetime.now(timezone.utc)
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _to_read(ticket, _engineer_names(db, [ticket]).get(ticket.assigned_engineer_id))


@router.get("/usage", response_model=PortalUsage)
def my_package_usage(
    contact: Contact = Depends(get_current_contact), db: Session = Depends(get_db)
) -> PortalUsage:
    """Section 7: hour-package status, but only when the organization allows
    this contact to see organization-wide data - package consumption is a
    commercial figure for the whole company, not a personal one."""
    if not contact.can_view_org_tickets:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Просмотр расхода часов не включён для вашей учётной записи",
        )
    contract, _, has_no_active_contract = resolve_contract_and_tariff(db, contact.organization_id)
    if contract is None or has_no_active_contract:
        return PortalUsage(has_contract=False)
    today = date.today()
    usage = billing.get_organization_usage(db, contact.organization_id, contract, today.year, today.month)
    return PortalUsage(
        has_contract=True,
        package_total_hours=round(usage["package_total_minutes"] / 60, 2),
        package_used_hours=round(usage["package_used_minutes"] / 60, 2),
        package_remaining_hours=round(usage["package_remaining_minutes"] / 60, 2),
        overage_hours=round(usage["overage_minutes"] / 60, 2),
    )
