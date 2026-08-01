from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class SavedFilter(Base, TimestampMixin):
    """A named set of queue filters (section 8.1 "сохраняемые фильтры").

    Per-user rather than global: "мои просроченные" means something different
    for each engineer, and a shared list would fill up with other people's
    views. Criteria are stored as JSON because they mirror the query
    parameters of GET /tickets exactly - promoting them to columns would mean
    a migration every time a new filter is added to the queue."""

    __tablename__ = "saved_filters"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_filters_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    criteria: Mapped[dict] = mapped_column(JSON, default=dict)

    user: Mapped["User"] = relationship()
