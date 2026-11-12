"""Staff MAX binding and new-ticket subscription."""
from alembic import op
import sqlalchemy as sa

revision = 'b8c4d2e901a6'
down_revision = 'a7b3e9f102c4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('max_id', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('max_chat_id', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('max_link_code_hash', sa.String(64), nullable=True))
    op.add_column('users', sa.Column('max_link_code_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('max_notify_new_tickets', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_unique_constraint('uq_users_max_id', 'users', ['max_id'])
    op.create_unique_constraint('uq_users_max_chat_id', 'users', ['max_chat_id'])
    op.create_unique_constraint('uq_users_max_link_code_hash', 'users', ['max_link_code_hash'])


def downgrade():
    for name in ('uq_users_max_link_code_hash', 'uq_users_max_chat_id', 'uq_users_max_id'):
        op.drop_constraint(name, 'users', type_='unique')
    for name in ('max_notify_new_tickets', 'max_link_code_expires_at', 'max_link_code_hash', 'max_chat_id', 'max_id'):
        op.drop_column('users', name)
