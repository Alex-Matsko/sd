from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Channel, MessageDirection
from app.models.base import Base


class Message(Base):
    __tablename__ = "messages"

    # Переписка грузится по ticket_id при каждом открытии карточки, а поиск
    # по тексту ходит сюда через EXISTS.
    __table_args__ = (Index("ix_messages_ticket_id", "ticket_id"), Index("uq_messages_request_key", "request_key", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    direction: Mapped[MessageDirection] = mapped_column(
        SAEnum(MessageDirection, native_enum=False, length=20, validate_strings=True)
    )
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, native_enum=False, length=20, validate_strings=True))
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    author_contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    body: Mapped[str] = mapped_column(Text)
    content_blocks: Mapped[list[dict] | None] = mapped_column(JSON)
    request_key: Mapped[str | None] = mapped_column(String(96))
    request_digest: Mapped[str | None] = mapped_column(String(64))
    # Email threading (section 2.3): the RFC 5322 Message-ID this message was
    # sent/received with, and the In-Reply-To header of an inbound message -
    # used to attach a client's reply to the right ticket ahead of the
    # [#ID]-in-subject fallback (services/email_channel.py).
    email_message_id: Mapped[str | None] = mapped_column(String(998))
    email_in_reply_to: Mapped[str | None] = mapped_column(String(998))
    # Quoting a specific message in the thread (staff UI and MAX both use
    # this): which other message THIS one is a reply to. Channel-agnostic,
    # unlike the email_* pair above - set directly on creation via
    # MessageCreate rather than inferred from a channel-native header.
    reply_to_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    # MAX's own per-message id (`mid`), stored for both inbound and outbound
    # messages so a reply in either direction can be resolved: an inbound
    # native MAX reply references this by mid (-> reply_to_message_id), and
    # an outbound reply to a message that arrived via MAX needs the parent's
    # mid to build the native `link` MAX itself renders as a reply.
    max_message_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # Same role as max_message_id, for Telegram's `message_id` - a plain
    # per-chat integer there (vs MAX's opaque `mid` string), used the same
    # way to resolve a reply in either direction (services/telegram_channel.py).
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")
    reply_to: Mapped["Message"] = relationship(remote_side="Message.id")
    channel_job: Mapped["ChannelJob | None"] = relationship(lazy="selectin", uselist=False)

    @property
    def is_automated(self):
        return bool(self.request_key and self.request_key.startswith("automation:"))

    @property
    def delivery(self):
        job = self.channel_job
        return job if job is not None and job.kind == "outbound" else None

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
