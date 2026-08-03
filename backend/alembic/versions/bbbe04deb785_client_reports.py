"""Отчёты клиентам: хранимые снимки за период (ТЗ 9.2)

Revision ID: bbbe04deb785
Revises: c3e91a5d70f4
Create Date: 2026-08-03 11:24:33.259720

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'bbbe04deb785'
down_revision: Union[str, None] = 'c3e91a5d70f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('client_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('generated_by_user_id', sa.Integer(), nullable=True),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_by_user_id', sa.Integer(), nullable=True),
    sa.Column('tickets_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['generated_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['sent_by_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'period_start', 'period_end', name='uq_client_report_period')
    )
    op.create_index('ix_client_reports_organization_period', 'client_reports', ['organization_id', 'period_start'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_client_reports_organization_period', table_name='client_reports')
    op.drop_table('client_reports')
