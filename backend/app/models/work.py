"""Planned work is independent of incident SLA and billing."""
from datetime import date, datetime

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class WorkProject(Base, TimestampMixin):
    __tablename__ = "work_projects"
    __table_args__ = (
        CheckConstraint("due_date IS NULL OR start_date IS NULL OR due_date >= start_date", name="ck_work_project_dates"),
        CheckConstraint("status IN ('draft','planning','approval','approved','in_progress','paused','completed','cancelled')", name="ck_work_project_status"),
        Index("ix_work_projects_status_due", "status", "due_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    approval_round: Mapped[int] = mapped_column(default=0, server_default="0")
    tasks: Mapped[list["WorkTask"]] = relationship(order_by="WorkTask.id", lazy="selectin")
    approvals: Mapped[list["WorkApproval"]] = relationship(order_by="WorkApproval.id", lazy="select")


class WorkTask(Base, TimestampMixin):
    __tablename__ = "work_tasks"
    __table_args__ = (
        CheckConstraint("due_date IS NULL OR start_date IS NULL OR due_date >= start_date", name="ck_work_task_dates"),
        CheckConstraint("estimate_minutes >= 0 AND actual_minutes >= 0", name="ck_work_task_minutes"),
        CheckConstraint("status IN ('backlog','ready','in_progress','review','done','cancelled')", name="ck_work_task_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("work_projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    stage: Mapped[str] = mapped_column(String(100), default="Основной этап", server_default="Основной этап")
    status: Mapped[str] = mapped_column(String(20), default="backlog", server_default="backlog")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    estimate_minutes: Mapped[int] = mapped_column(default=0, server_default="0")
    actual_minutes: Mapped[int] = mapped_column(default=0, server_default="0")
    completion_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkDependency(Base):
    __tablename__ = "work_dependencies"
    __table_args__ = (CheckConstraint("task_id != depends_on_id", name="ck_work_dependency_self"),)
    task_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id", ondelete="CASCADE"), primary_key=True)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey("work_tasks.id", ondelete="CASCADE"), primary_key=True)


class WorkApproval(Base):
    __tablename__ = "work_approvals"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) != (contact_id IS NULL)", name="ck_work_approval_actor"),
        CheckConstraint("state IN ('pending','approved','rejected','superseded')", name="ck_work_approval_state"),
        UniqueConstraint("project_id", "round", "user_id", name="uq_work_approval_user"),
        UniqueConstraint("project_id", "round", "contact_id", name="uq_work_approval_contact"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("work_projects.id", ondelete="CASCADE"), index=True)
    round: Mapped[int]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    approver_name: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    snapshot: Mapped[dict] = mapped_column(JSON)
    comment: Mapped[str] = mapped_column(Text, default="", server_default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkTicketLink(Base):
    __tablename__ = "work_ticket_links"
    project_id: Mapped[int] = mapped_column(ForeignKey("work_projects.id", ondelete="CASCADE"), primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True)


class WorkComment(Base):
    __tablename__ = "work_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("work_projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
