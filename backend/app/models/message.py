from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Channel, MessageDirection
from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    direction: Mapped[MessageDirection] = mapped_column(
        SAEnum(MessageDirection, native_enum=False, length=20, validate_strings=True)
    )
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, native_enum=False, length=20, validate_strings=True))
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    author_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    body: Mapped[str] = mapped_column(Text)
    # Email threading (section 2.3): the RFC 5322 Message-ID this message was
    # sent/received with, and the In-Reply-To header of an inbound message -
    # used to attach a client's reply to the right ticket ahead of the
    # [#ID]-in-subject fallback (services/email_channel.py).
    email_message_id: Mapped[str | None] = mapped_column(String(998))
    email_in_reply_to: Mapped[str | None] = mapped_column(String(998))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="message", cascade="all, delete-orphan")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["Message"] = relationship(back_populates="attachments")
