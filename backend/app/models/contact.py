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
    can_view_org_tickets: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    organization: Mapped["Organization"] = relationship(back_populates="contacts")
    emails: Mapped[list["ContactEmail"]] = relationship(back_populates="contact", cascade="all, delete-orphan")
    phones: Mapped[list["ContactPhone"]] = relationship(back_populates="contact", cascade="all, delete-orphan")

    # Доступ в личный кабинет. selectin, а не ленивая загрузка: список
    # контактов иначе делал бы запрос на каждую строку ради одного флага.
    portal_credential: Mapped["PortalCredential | None"] = relationship(
        "PortalCredential", uselist=False, lazy="selectin", viewonly=True
    )

    @property
    def has_portal_access(self) -> bool:
        """Выдан ли доступ в кабинет. Без этого признака диспетчер не видит
        в списке, кому доступ уже дан, — и выдаёт повторно или не выдаёт."""
        return self.portal_credential is not None and bool(self.portal_credential.password_hash)


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
