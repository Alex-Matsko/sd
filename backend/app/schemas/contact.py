from pydantic import BaseModel, ConfigDict


class ContactCreate(BaseModel):
    organization_id: int
    full_name: str
    position: str | None = None
    telegram_id: str | None = None
    max_id: str | None = None
    is_vip: bool = False
    can_view_org_tickets: bool = False
    is_confirmed: bool = True
    emails: list[str] = []
    phones: list[str] = []


class ContactUpdate(BaseModel):
    full_name: str | None = None
    position: str | None = None
    telegram_id: str | None = None
    max_id: str | None = None
    is_vip: bool | None = None
    can_view_org_tickets: bool | None = None
    is_confirmed: bool | None = None


class ContactEmailRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_primary: bool


class ContactPhoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    is_primary: bool


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    full_name: str
    position: str | None
    telegram_id: str | None
    max_id: str | None
    is_vip: bool
    can_view_org_tickets: bool
    is_confirmed: bool
    emails: list[ContactEmailRead] = []
    phones: list[ContactPhoneRead] = []
