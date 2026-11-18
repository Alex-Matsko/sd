"""Persistent session revocation and valid work durations."""
from alembic import op
import sqlalchemy as sa

revision = 'f42ad8e567bc'
down_revision = 'f319c7d456fb'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('auth_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('contacts', sa.Column('portal_auth_version', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('contacts', sa.Column('portal_access_revoked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_check_constraint('ck_time_entries_positive_duration', 'time_entries', 'duration_minutes > 0')
    op.create_check_constraint('ck_time_entries_nonnegative_billing', 'time_entries', 'billed_package_minutes >= 0 AND billed_overage_minutes >= 0')


def downgrade():
    op.drop_constraint('ck_time_entries_nonnegative_billing', 'time_entries', type_='check')
    op.drop_constraint('ck_time_entries_positive_duration', 'time_entries', type_='check')
    op.drop_column('contacts', 'portal_access_revoked')
    op.drop_column('contacts', 'portal_auth_version')
    op.drop_column('users', 'auth_version')
