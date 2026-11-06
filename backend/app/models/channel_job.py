"""Durable inbox/outbox shared by API and independently running workers."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChannelJob(Base, TimestampMixin):
    __tablename__ = "channel_jobs"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_channel_jobs_event_key"),
        UniqueConstraint("message_id", name="uq_channel_jobs_message_id"),
        Index("ix_channel_jobs_ready", "kind", "state", "available_at"),
        Index("ix_channel_jobs_stream", "kind", "stream_key", "id"),
        Index("ix_channel_jobs_ticket_id", "ticket_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(20))
    event_key: Mapped[str] = mapped_column(String(255))
    stream_key: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_body: Mapped[bytes | None] = mapped_column(LargeBinary)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class WorkerPulse(Base):
    __tablename__ = "worker_pulses"
    component: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    expected_interval: Mapped[int] = mapped_column(default=60, server_default="60")
