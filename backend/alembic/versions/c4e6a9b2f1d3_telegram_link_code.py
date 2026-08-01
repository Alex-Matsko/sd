"""self-service Telegram linking code for engineers (section 8)

Revision ID: c4e6a9b2f1d3
Revises: b3d5f8a1c2e7
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4e6a9b2f1d3'
down_revision: Union[str, None] = 'b3d5f8a1c2e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('telegram_link_code', sa.String(length=16), nullable=True))
    op.add_column('users', sa.Column('telegram_link_code_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint('uq_users_telegram_link_code', 'users', ['telegram_link_code'])


def downgrade() -> None:
    op.drop_constraint('uq_users_telegram_link_code', 'users', type_='unique')
    op.drop_column('users', 'telegram_link_code_expires_at')
    op.drop_column('users', 'telegram_link_code')
