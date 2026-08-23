"""Убрана метка VIP у контакта: она ни на что не влияла

Revision ID: 286792ad543b
Revises: d152e64b5b3f
Create Date: 2026-08-23 07:20:42.466990

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '286792ad543b'
down_revision: Union[str, None] = 'd152e64b5b3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('contacts', 'is_vip')


def downgrade() -> None:
    op.add_column('contacts', sa.Column('is_vip', sa.BOOLEAN(), server_default=sa.text('false'), autoincrement=False, nullable=False))
