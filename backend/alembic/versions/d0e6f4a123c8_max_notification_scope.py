"""MAX notification scope with preservation of existing subscriptions."""
from alembic import op
import sqlalchemy as sa

revision = 'd0e6f4a123c8'
down_revision = 'c9d5e3f012b7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('max_notification_scope', sa.String(16), nullable=False, server_default='off'))
    op.execute("""UPDATE users SET max_notification_scope = CASE
        WHEN max_notify_new_tickets THEN CASE WHEN role = 'ENGINEER' THEN 'assigned' ELSE 'all' END
        ELSE 'off' END""")


def downgrade():
    op.drop_column('users', 'max_notification_scope')
