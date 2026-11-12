"""Personal Telegram notification scope."""
from alembic import op
import sqlalchemy as sa
revision = 'c9d5e3f012b7'
down_revision = 'b8c4d2e901a6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('telegram_notification_scope', sa.String(16), nullable=False, server_default='assigned'))


def downgrade():
    op.drop_column('users', 'telegram_notification_scope')
