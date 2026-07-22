from sqlalchemy import Boolean, Enum as SAEnum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Channel
from app.models.base import Base, TimestampMixin


class ChannelConversationState(Base, TimestampMixin):
    """Per-conversation bot state for messenger channels (Telegram/MAX, section
    2, "Склейка диалога"): which ticket subsequent messages from this external
    user attach to, and whether the bot is waiting on a reply to its own
    "which ticket is this about?" question. One row per (channel,
    external_user_id) - the messenger-side identity, not the resolved Contact,
    since a message can arrive before a contact exists (unknown-senders queue).
    """

    __tablename__ = "channel_conversation_states"
    __table_args__ = (UniqueConstraint("channel", "external_user_id", name="uq_channel_conversation_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, native_enum=False, length=20, validate_strings=True))
    # Messenger-native user id (Telegram user id / MAX user_id) - matched
    # against Contact.telegram_id / Contact.max_id to resolve identity.
    external_user_id: Mapped[str] = mapped_column(String(64))
    # Messenger-native chat id to send replies to - distinct from the user id
    # on platforms where a bot addresses a chat rather than a user directly.
    chat_id: Mapped[str] = mapped_column(String(64))
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    active_ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    awaiting_ticket_choice: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    awaiting_new_ticket_text: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
