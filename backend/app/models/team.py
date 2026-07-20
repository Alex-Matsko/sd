from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Team(Base, TimestampMixin):
    """Engineer group. Not explicit in the original spec's data model (section 3),
    but required for category-based routing and for 100%-SLA escalation to the
    team lead (section 4.3/4.4)."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    lead_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    memberships: Mapped[list["TeamMembership"]] = relationship(back_populates="team", cascade="all, delete-orphan")
