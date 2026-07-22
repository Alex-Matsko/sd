"""stage 4: email channel - integration settings table, message threading headers

Revision ID: c58a2e916b04
Revises: b41f7c02d9e1
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c58a2e916b04'
down_revision: Union[str, None] = 'b41f7c02d9e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'integration_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.Enum(
            'telegram', 'max', 'email', 'phone', 'portal', 'whatsapp',
            name='channel', native_enum=False, length=20,
        ), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('secrets_encrypted', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel'),
    )

    op.add_column('messages', sa.Column('email_message_id', sa.String(length=998), nullable=True))
    op.add_column('messages', sa.Column('email_in_reply_to', sa.String(length=998), nullable=True))


def downgrade() -> None:
    op.drop_column('messages', 'email_in_reply_to')
    op.drop_column('messages', 'email_message_id')
    op.drop_table('integration_settings')
