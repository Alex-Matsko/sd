from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    telegram_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    max_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_vip: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    can_view_org_tickets: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    organization: Mapped["Organization"] = relationship(back_populates="contacts")
    emails: Mapped[list["ContactEmail"]] = relationship(back_populates="contact", cascade="all, delete-orphan")
    phones: Mapped[list["ContactPhone"]] = relationship(back_populates="contact", cascade="all, delete-orphan")


class ContactEmail(Base):
    __tablename__ = "contact_emails"
    __table_args__ = (UniqueConstraint("email", name="uq_contact_emails_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    contact: Mapped["Contact"] = relationship(back_populates="emails")


class ContactPhone(Base):
    __tablename__ = "contact_phones"
    __table_args__ = (UniqueConstraint("phone", name="uq_contact_phones_phone"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    phone: Mapped[str] = mapped_column(String(32))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    contact: Mapped["Contact"] = relationship(back_populates="phones")
