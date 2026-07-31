"""cross-channel identity matching: phone confirmation state

Revision ID: b3d5f8a1c2e7
Revises: a2c9e1f7b6d4
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3d5f8a1c2e7'
down_revision: Union[str, None] = 'a2c9e1f7b6d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'channel_conversation_states',
        sa.Column('awaiting_phone_confirmation', sa.Boolean(), server_default='false', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('channel_conversation_states', 'awaiting_phone_confirmation')
