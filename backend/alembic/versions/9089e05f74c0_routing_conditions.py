"""Условия в правилах маршрутизации: И/ИЛИ/НЕ вместо одного признака (ТЗ 4.4)

Revision ID: 9089e05f74c0
Revises: 286792ad543b
Create Date: 2026-08-23 09:06:20.150321

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '9089e05f74c0'
down_revision: Union[str, None] = '286792ad543b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('routing_rules', sa.Column('name', sa.String(length=255), nullable=True))
    op.add_column('routing_rules', sa.Column('match', sa.String(length=3), server_default='all', nullable=False))
    op.add_column('routing_rules', sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('routing_rules', 'conditions')
    op.drop_column('routing_rules', 'match')
    op.drop_column('routing_rules', 'name')
