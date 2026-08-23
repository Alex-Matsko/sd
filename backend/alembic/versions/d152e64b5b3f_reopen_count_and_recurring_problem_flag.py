"""Счётчик переоткрытий (ITIL reopen rate) и метка «повторяющаяся проблема» (ТЗ р. 4)

Revision ID: d152e64b5b3f
Revises: bbbe04deb785
Create Date: 2026-08-23 06:24:32.104679

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd152e64b5b3f'
down_revision: Union[str, None] = 'bbbe04deb785'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tickets', sa.Column('reopen_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('tickets', sa.Column('is_recurring_problem', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('tickets', 'is_recurring_problem')
    op.drop_column('tickets', 'reopen_count')
