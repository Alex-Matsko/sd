"""stage 3: SLA engine - escalation stamps, working-minute pause total, notifications

Revision ID: b41f7c02d9e1
Revises: a3255dd9c877
Create Date: 2026-07-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b41f7c02d9e1'
down_revision: Union[str, None] = 'a3255dd9c877'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tickets',
        sa.Column('sla_paused_working_minutes_total', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column('tickets', sa.Column('sla_reaction_warned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tickets', sa.Column('sla_reaction_escalated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tickets', sa.Column('sla_resolution_warned_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tickets', sa.Column('sla_resolution_escalated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=True),
        sa.Column('type', sa.Enum(
            'sla_reaction_warning', 'sla_reaction_breach', 'sla_resolution_warning', 'sla_resolution_breach',
            name='notificationtype', native_enum=False, length=40,
        ), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_notifications_user_id'), 'notifications', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_notifications_user_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_column('tickets', 'sla_resolution_escalated_at')
    op.drop_column('tickets', 'sla_resolution_warned_at')
    op.drop_column('tickets', 'sla_reaction_escalated_at')
    op.drop_column('tickets', 'sla_reaction_warned_at')
    op.drop_column('tickets', 'sla_paused_working_minutes_total')
