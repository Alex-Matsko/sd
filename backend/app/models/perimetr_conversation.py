from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PerimetrConversation(Base, TimestampMixin):
    """Переписка из окна «Поддержка» продукта «Периметр».

    Ключ задаёт служба продукта: `cloud:<организация>` у облака,
    `vms:<хеш ключа установки>` у серверов VMS. Одна переписка — один
    клиент на стороне продукта; заявки внутри неё меняются: пока заявка
    открыта, сообщения идут в неё, после закрытия следующее сообщение
    открывает новую. Как у мессенджеров (ChannelConversationState), но без
    кнопок бота: выбирать заявку в окне продукта клиенту не нужно.
    """

    __tablename__ = "perimetr_conversations"
    __table_args__ = (Index("ix_perimetr_conversations_active_ticket_id", "active_ticket_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    # «Периметр VMS» или «Периметр Облако» — подпись в теме заявки.
    product: Mapped[str] = mapped_column(String(64))
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    active_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))


class PerimetrConversationTicket(Base):
    """Заявки переписки. Ответы продукт читает строго по ним, а не по
    контакту: адрес для ответа на сервере VMS вписывает кто угодно, и
    поиск по контакту отдал бы чужому серверу чужую переписку."""

    __tablename__ = "perimetr_conversation_tickets"
    __table_args__ = (
        UniqueConstraint("conversation_id", "ticket_id", name="uq_perimetr_conversation_ticket"),
        Index("ix_perimetr_conversation_tickets_ticket_id", "ticket_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("perimetr_conversations.id", ondelete="CASCADE"))
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
