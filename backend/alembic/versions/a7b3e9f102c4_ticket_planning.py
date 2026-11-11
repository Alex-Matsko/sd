"""Planned deadline and effort estimate, independent from contractual SLA."""
from alembic import op
import sqlalchemy as sa
revision = "a7b3e9f102c4"
down_revision = "d4f8a1b2c3e6"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('tickets', sa.Column('planned_due_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tickets', sa.Column('estimated_minutes', sa.Integer(), nullable=True))
    op.create_check_constraint('ck_tickets_estimated_minutes', 'tickets', 'estimated_minutes IS NULL OR estimated_minutes >= 0')

def downgrade():
    op.drop_constraint('ck_tickets_estimated_minutes', 'tickets', type_='check')
    op.drop_column('tickets', 'estimated_minutes')
    op.drop_column('tickets', 'planned_due_at')
