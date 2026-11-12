from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserRole
from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole, native_enum=False, length=20, validate_strings=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    telegram_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    telegram_notification_scope: Mapped[str] = mapped_column(String(16), default="assigned", server_default="assigned")
    # Self-service linking (section 8: "инженер привязывает свой TG в профиле"):
    # a short-lived one-time code shown in the profile page, sent to the bot
    # as "/link <code>" (services/telegram_channel.py) to set telegram_id
    # without needing an admin to set it via user management.
    telegram_link_code: Mapped[str | None] = mapped_column(String(16), unique=True)
    telegram_link_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    max_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    max_chat_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    max_link_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    max_link_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_notification_scope: Mapped[str] = mapped_column(String(16), default="off", server_default="off")
    max_notify_new_tickets: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    @property
    def max_linked(self) -> bool:
        return bool(self.max_id and self.max_chat_id)

    team_memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class TeamMembership(Base):
    __tablename__ = "team_memberships"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)

    user: Mapped["User"] = relationship(back_populates="team_memberships")
    team: Mapped["Team"] = relationship(back_populates="memberships")
