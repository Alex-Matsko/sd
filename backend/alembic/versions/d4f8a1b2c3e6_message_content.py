"""Ordered text and original image blocks in messages."""
from alembic import op
import sqlalchemy as sa

revision = "d4f8a1b2c3e6"
down_revision = "892f52a64ed9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("content_blocks", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("messages", "content_blocks")
