from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, func, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import NotificationType
from app.models.base import Base


class Notification(Base):
    """In-app notification for a staff user (SLA escalations in Stage 3;
    delivery to personal Telegram is added in Stage 4). Read state is per-row -
    a notification belongs to exactly one user."""

    __tablename__ = "notifications"

    # Индекс на внешний ключ к tickets: без него удаление заявки
    # проверяет эту таблицу полным перебором (миграция c3e91a5d70f4).
    __table_args__ = (Index("ix_notifications_ticket_id", "ticket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("work_projects.id", ondelete="CASCADE"), index=True)
    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType, native_enum=False, length=40, validate_strings=True)
    )
    title: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
