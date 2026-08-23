from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class PortalCredential(Base, TimestampMixin):
    """Client-portal login for a Contact (section 7: "вход по email + пароль
    или magic-link на почту").

    Deliberately separate from `User`: staff and clients are different
    populations with different lifecycles, and a client must never end up
    holding a token that the staff API would accept. Keeping the identity in
    its own table means the portal's tokens carry a different subject type
    and can't be confused for a staff session.

    One row per contact; the email that logs in is looked up through the
    contact's own addresses, so no address is duplicated here."""

    __tablename__ = "portal_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), unique=True)
    # Null when the client has only ever used magic links - a perfectly valid
    # state, so login has to cope with "no password set" rather than assume one.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Когда клиент последний раз смотрел свои заявки. По этой отметке
    # считается, что для него новое: без неё «непрочитанное» пришлось бы
    # хранить по каждому сообщению отдельно ради сводки на одной странице.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped["Contact"] = relationship()


class PortalLoginToken(Base):
    """Single-use magic-link token e-mailed to a client (section 7).

    Stored hashed, like staff refresh tokens: a leaked database row must not
    be usable as a login. `used_at` makes it single-use - without it a link
    sitting in a mailbox stays a valid credential for its whole lifetime."""

    __tablename__ = "portal_login_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
