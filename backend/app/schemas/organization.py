from pydantic import BaseModel, ConfigDict

from app.core.enums import OrganizationStatus


class OrganizationCreate(BaseModel):
    name: str
    legal_name: str | None = None
    status: OrganizationStatus = OrganizationStatus.ACTIVE
    account_manager_id: int | None = None
    email_domains: list[str] = []


class OrganizationUpdate(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    status: OrganizationStatus | None = None
    account_manager_id: int | None = None


class OrganizationEmailDomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    domain: str


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    legal_name: str | None
    status: OrganizationStatus
    account_manager_id: int | None
    email_domains: list[OrganizationEmailDomainRead] = []
