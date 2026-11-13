from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class MessengerReply(Base):
    """Provider reply identifiers for every delivered part, including notices/files."""
    __tablename__ = 'messenger_replies'
    __table_args__ = (UniqueConstraint('channel', 'account', 'chat_id', 'external_message_id', name='uq_messenger_reply'),
                     Index('ix_messenger_replies_ticket_id', 'ticket_id'))
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))
    account: Mapped[str] = mapped_column(String(20))
    chat_id: Mapped[str] = mapped_column(String(128))
    external_message_id: Mapped[str] = mapped_column(String(128))
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id', ondelete='CASCADE'))
    contact_id: Mapped[int] = mapped_column(ForeignKey('contacts.id', ondelete='CASCADE'))
    message_id: Mapped[int | None] = mapped_column(ForeignKey('messages.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
