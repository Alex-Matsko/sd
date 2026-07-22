"""stage 5: MAX channel - conversation state table, CSAT columns on tickets

Revision ID: d71e4a3f0b2c
Revises: c58a2e916b04
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd71e4a3f0b2c'
down_revision: Union[str, None] = 'c58a2e916b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tickets', sa.Column('csat_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tickets', sa.Column('csat_rating', sa.Integer(), nullable=True))
    op.add_column('tickets', sa.Column('csat_rated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'channel_conversation_states',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel', sa.Enum(
            'telegram', 'max', 'email', 'phone', 'portal', 'whatsapp',
            name='channel', native_enum=False, length=20,
        ), nullable=False),
        sa.Column('external_user_id', sa.String(length=64), nullable=False),
        sa.Column('chat_id', sa.String(length=64), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('active_ticket_id', sa.Integer(), nullable=True),
        sa.Column('awaiting_ticket_choice', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('awaiting_new_ticket_text', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['active_ticket_id'], ['tickets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('channel', 'external_user_id', name='uq_channel_conversation_identity'),
    )


def downgrade() -> None:
    op.drop_table('channel_conversation_states')
    op.drop_column('tickets', 'csat_rated_at')
    op.drop_column('tickets', 'csat_rating')
    op.drop_column('tickets', 'csat_requested_at')
