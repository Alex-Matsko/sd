from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Category(Base):
    """Two-level configurable category tree (section 4.1). Top-level categories
    have parent_id=None; a category that already has a parent may not itself be
    used as a parent (enforced in the service layer, not at the DB level)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(String(255))

    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    parent: Mapped["Category"] = relationship(back_populates="children", remote_side="Category.id")
