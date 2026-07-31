"""telegram channel: per-message id for reply resolution

Revision ID: a2c9e1f7b6d4
Revises: f1a2b3c4d5e6
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2c9e1f7b6d4'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('messages', sa.Column('telegram_message_id', sa.Integer(), nullable=True))
    op.create_index('ix_messages_telegram_message_id', 'messages', ['telegram_message_id'])


def downgrade() -> None:
    op.drop_index('ix_messages_telegram_message_id', table_name='messages')
    op.drop_column('messages', 'telegram_message_id')
