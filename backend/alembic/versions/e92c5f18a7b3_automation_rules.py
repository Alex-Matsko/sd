"""automation rules (Kanban auto-move / auto-close, section 4.2)

Revision ID: e92c5f18a7b3
Revises: d71e4a3f0b2c
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e92c5f18a7b3'
down_revision: Union[str, None] = 'd71e4a3f0b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_ENUM = sa.Enum(
    'new', 'assigned', 'in_progress', 'waiting_customer', 'waiting_third_party',
    'resolved', 'closed', 'cancelled',
    name='ticketstatus', native_enum=False, length=30,
)


def upgrade() -> None:
    op.create_table(
        'automation_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('trigger_type', sa.Enum(
            'resolved_without_reply', name='automationtriggertype', native_enum=False, length=40,
        ), nullable=False),
        sa.Column('from_status', _STATUS_ENUM, nullable=False),
        sa.Column('to_status', _STATUS_ENUM, nullable=False),
        sa.Column('threshold_days', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('automation_rules')
