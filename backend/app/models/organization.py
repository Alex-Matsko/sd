from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import OrganizationStatus
from app.models.base import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    legal_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[OrganizationStatus] = mapped_column(
        SAEnum(OrganizationStatus, native_enum=False, length=20, validate_strings=True),
        default=OrganizationStatus.ACTIVE,
        server_default=OrganizationStatus.ACTIVE.value,
    )
    account_manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    email_domains: Mapped[list["OrganizationEmailDomain"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    contacts: Mapped[list["Contact"]] = relationship(back_populates="organization")
    contracts: Mapped[list["Contract"]] = relationship(back_populates="organization")
    assets: Mapped[list["Asset"]] = relationship(back_populates="organization")


class OrganizationEmailDomain(Base):
    """Corporate email domain registered on an organization, used for auto-linking
    inbound mail from unknown senders. Public domains (gmail.com etc.) must never
    be registered here - see PublicEmailDomain."""

    __tablename__ = "organization_email_domains"
    __table_args__ = (UniqueConstraint("domain", name="uq_organization_email_domains_domain"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    domain: Mapped[str] = mapped_column(String(255))

    organization: Mapped["Organization"] = relationship(back_populates="email_domains")


class PublicEmailDomain(Base):
    """Registry of public mail domains (gmail.com, yandex.ru, mail.ru, ...) excluded
    from automatic domain-based organization linking - mail from these goes to the
    unknown-senders queue instead."""

    __tablename__ = "public_email_domains"

    domain: Mapped[str] = mapped_column(String(255), primary_key=True)
