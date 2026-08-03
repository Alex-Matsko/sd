from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ClientReport(Base, TimestampMixin):
    """Сформированный отчёт клиенту за период (ТЗ 9.2).

    Хранится **снимком данных**, а не ссылкой на период. Отчёт — документ,
    который уходит клиенту: если пересчитывать его на лету, то списанное
    задним числом время или переоткрытая заявка молча изменят цифры за
    прошлый месяц, уже отправленные наружу. Снимок фиксирует то, что было
    на момент формирования; чтобы получить актуальные цифры, отчёт нужно
    сформировать заново — явным действием.

    Ключ (организация, начало, конец) уникален: повторный проход воркера
    первого числа не должен плодить дубликаты за один и тот же месяц.
    """

    __tablename__ = "client_reports"

    __table_args__ = (
        UniqueConstraint("organization_id", "period_start", "period_end", name="uq_client_report_period"),
        Index("ix_client_reports_organization_period", "organization_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)

    # Полный ответ get_client_report на момент формирования.
    data: Mapped[dict] = mapped_column(JSONB)

    # Сформирован вручную или автоматическим проходом первого числа.
    # Нужно, чтобы в списке было видно, что руководитель уже переформировал
    # отчёт после исправления списаний.
    generated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), default="manual")

    # Отметка «отправлен» ставится руками: рассылки нет, но руководителю
    # нужно помнить, какие отчёты он уже разослал, а какие нет.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    tickets_count: Mapped[int] = mapped_column(Integer, default=0)
