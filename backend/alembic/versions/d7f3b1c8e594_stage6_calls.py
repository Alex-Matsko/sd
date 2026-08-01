"""stage 6: telephony calls (Plusofon)

Revision ID: d7f3b1c8e594
Revises: c4e6a9b2f1d3
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7f3b1c8e594'
down_revision: Union[str, None] = 'c4e6a9b2f1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(length=128), nullable=False),
        sa.Column('direction', sa.Enum(
            'inbound', 'outbound', name='calldirection', native_enum=False, length=20,
        ), nullable=False),
        sa.Column('status', sa.Enum(
            'ringing', 'answered', 'completed', 'missed', 'failed',
            name='callstatus', native_enum=False, length=20,
        ), nullable=False),
        sa.Column('from_number', sa.String(length=32), nullable=False),
        sa.Column('to_number', sa.String(length=32), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('recording_url', sa.String(length=1000), nullable=True),
        sa.Column('contact_id', sa.Integer(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('ticket_id', sa.Integer(), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_calls_external_id', 'calls', ['external_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_calls_external_id', table_name='calls')
    op.drop_table('calls')
