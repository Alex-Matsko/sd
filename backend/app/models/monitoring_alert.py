from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MonitoringAlert(Base, TimestampMixin):
    """An alert received from a monitoring system (Zabbix and friends) -
    по запросу заказчика, вне исходного ТЗ.

    Kept as its own record rather than only a ticket, because monitoring is
    chatty: the same problem flaps, and the recovery event has to find the
    alert it belongs to. `external_id` (the monitoring system's own event or
    trigger id) is what makes ingestion idempotent - a re-fired alert must
    update the existing record, not open a second ticket for one outage."""

    __tablename__ = "monitoring_alerts"

    # Индекс на внешний ключ к tickets: без него удаление заявки
    # проверяет эту таблицу полным перебором (миграция c3e91a5d70f4).
    __table_args__ = (Index("ix_monitoring_alerts_ticket_id", "ticket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), default="monitoring")
    severity: Mapped[str | None] = mapped_column(String(32))
    host: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)

    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organization: Mapped["Organization"] = relationship()
    ticket: Mapped["Ticket"] = relationship()
