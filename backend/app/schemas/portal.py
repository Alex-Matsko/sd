from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.core.enums import Priority, TicketStatus


class PortalLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PortalMagicLinkRequest(BaseModel):
    email: EmailStr


class PortalTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PortalMe(BaseModel):
    contact_id: int
    full_name: str
    organization: str
    can_view_org_tickets: bool


class PortalPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class PortalTicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=500)
    body: str = Field(min_length=1)
    category_id: int | None = None


class PortalMessageCreate(BaseModel):
    body: str = Field(min_length=1)


class PortalRatingRequest(BaseModel):
    rating: int = Field(ge=1, le=5)


class PortalMessageRead(BaseModel):
    id: int
    body: str
    # The portal never exposes which engineer wrote a reply - the client deals
    # with "поддержка", and staff names are internal.
    is_from_support: bool
    created_at: datetime
    attachments: list["PortalAttachmentRead"] = []


class PortalAttachmentRead(BaseModel):
    id: int
    filename: str
    size_bytes: int


class PortalTicketRead(BaseModel):
    id: int
    display_number: str
    subject: str
    status: TicketStatus
    priority: Priority
    created_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None
    csat_rating: int | None
    # Кто ведёт заявку. Боты об этом клиенту сообщают, а в кабинете было не
    # видно — клиент не знал, к кому обращаться. Имена инженеров скрыты
    # только в отчётах (там это сравнение сотрудников между собой), в своей
    # заявке видеть исполнителя нормально.
    assigned_engineer_name: str | None = None


class PortalTicketDetail(PortalTicketRead):
    messages: list[PortalMessageRead]


class PortalTicketUpdate(BaseModel):
    ticket_id: int
    display_number: str
    subject: str
    status: TicketStatus
    new_messages: int
    status_changed: bool
    at: datetime


class PortalUpdates(BaseModel):
    """Что изменилось с прошлого визита клиента.

    Клиент не сидит в кабинете постоянно: без такой сводки он узнаёт об
    ответе, только если сам откроет заявку и заметит новое сообщение.
    """

    total_new_messages: int
    tickets: list[PortalTicketUpdate]


class PortalUsage(BaseModel):
    has_contract: bool
    package_total_hours: float | None = None
    package_used_hours: float | None = None
    package_remaining_hours: float | None = None
    overage_hours: float | None = None
