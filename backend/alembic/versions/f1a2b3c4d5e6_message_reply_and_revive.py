"""message reply threading (quoting) + MAX message ids + ticket revival state

Revision ID: f1a2b3c4d5e6
Revises: e92c5f18a7b3
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e92c5f18a7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('reply_to_message_id', sa.Integer(), nullable=True))
    op.add_column('messages', sa.Column('max_message_id', sa.String(length=64), nullable=True))
    op.create_foreign_key(
        'fk_messages_reply_to_message_id', 'messages', 'messages', ['reply_to_message_id'], ['id']
    )
    op.create_index('ix_messages_max_message_id', 'messages', ['max_message_id'])

    op.add_column(
        'channel_conversation_states',
        sa.Column('awaiting_revive_text', sa.Boolean(), server_default='false', nullable=False),
    )
    op.add_column(
        'channel_conversation_states', sa.Column('revive_parent_ticket_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_ccs_revive_parent_ticket_id', 'channel_conversation_states', 'tickets', ['revive_parent_ticket_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_ccs_revive_parent_ticket_id', 'channel_conversation_states', type_='foreignkey')
    op.drop_column('channel_conversation_states', 'revive_parent_ticket_id')
    op.drop_column('channel_conversation_states', 'awaiting_revive_text')

    op.drop_index('ix_messages_max_message_id', table_name='messages')
    op.drop_constraint('fk_messages_reply_to_message_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'max_message_id')
    op.drop_column('messages', 'reply_to_message_id')
