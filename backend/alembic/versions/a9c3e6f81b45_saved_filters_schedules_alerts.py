"""saved queue filters (8.1), recurring ticket schedules and monitoring alerts

Revision ID: a9c3e6f81b45
Revises: f8a1d4e7c206
Create Date: 2026-08-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9c3e6f81b45'
down_revision: Union[str, None] = 'f8a1d4e7c206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'saved_filters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('criteria', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'name', name='uq_saved_filters_user_name'),
    )

    op.create_table(
        'ticket_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=True),
        sa.Column('assigned_engineer_id', sa.Integer(), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('type', sa.Enum(
            'incident', 'service_request', name='tickettype', native_enum=False, length=20,
        ), nullable=False),
        sa.Column('priority', sa.Enum('P1', 'P2', 'P3', 'P4', name='priority', native_enum=False, length=2), nullable=False),
        sa.Column('cadence', sa.Enum(
            'daily', 'weekly', 'monthly', 'quarterly', name='schedulecadence', native_enum=False, length=20,
        ), nullable=False),
        sa.Column('day_of_week', sa.Integer(), nullable=True),
        sa.Column('day_of_month', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('next_run_on', sa.Date(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['assigned_engineer_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'monitoring_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('severity', sa.String(length=32), nullable=True),
        sa.Column('host', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('ticket_id', sa.Integer(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_monitoring_alerts_external_id', 'monitoring_alerts', ['external_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_monitoring_alerts_external_id', table_name='monitoring_alerts')
    op.drop_table('monitoring_alerts')
    op.drop_table('ticket_schedules')
    op.drop_table('saved_filters')
