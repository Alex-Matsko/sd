"""Периметр: переписка из окна «Поддержка» продуктов

Revision ID: c7d1e9a4b2f0
Revises: b74971b71858
Create Date: 2026-11-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d1e9a4b2f0'
down_revision: Union[str, None] = 'b74971b71858'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'perimetr_conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('product', sa.String(length=64), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('active_ticket_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['active_ticket_id'], ['tickets.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index('ix_perimetr_conversations_active_ticket_id', 'perimetr_conversations', ['active_ticket_id'])
    op.create_table(
        'perimetr_conversation_tickets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['perimetr_conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'ticket_id', name='uq_perimetr_conversation_ticket'),
    )
    op.create_index('ix_perimetr_conversation_tickets_ticket_id', 'perimetr_conversation_tickets', ['ticket_id'])


def downgrade() -> None:
    op.drop_index('ix_perimetr_conversation_tickets_ticket_id', table_name='perimetr_conversation_tickets')
    op.drop_table('perimetr_conversation_tickets')
    op.drop_index('ix_perimetr_conversations_active_ticket_id', table_name='perimetr_conversations')
    op.drop_table('perimetr_conversations')
