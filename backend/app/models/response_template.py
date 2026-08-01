from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ResponseTemplate(Base, TimestampMixin):
    """Canned reply an engineer can drop into a ticket (section 8.2 "быстрые
    ответы-шаблоны", 8.6). Optionally scoped to a category, so the picker in
    a ticket about 1С doesn't offer VPN boilerplate - templates without a
    category are offered everywhere."""

    __tablename__ = "response_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    category: Mapped["Category"] = relationship()
