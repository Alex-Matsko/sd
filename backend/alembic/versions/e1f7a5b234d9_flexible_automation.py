"""Flexible reminder rules and transactional execution journal."""
from alembic import op
import sqlalchemy as sa

revision = 'e1f7a5b234d9'
down_revision = 'd0e6f4a123c8'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('automation_rules', 'to_status', existing_type=sa.String(30), nullable=True)
    for column in [sa.Column('delay_hours', sa.Integer()), sa.Column('filters', sa.JSON(), nullable=False, server_default='{}'),
                   sa.Column('actions', sa.JSON(), nullable=False, server_default='[]'), sa.Column('repeat_hours', sa.Integer()),
                   sa.Column('max_runs', sa.Integer(), nullable=False, server_default='1'),
                   sa.Column('revision', sa.Integer(), nullable=False, server_default='1')]:
        op.add_column('automation_rules', column)
    op.create_table('automation_runs', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('rule_id', sa.Integer(), sa.ForeignKey('automation_rules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False), sa.Column('episode', sa.String(64), nullable=False),
        sa.Column('occurrence', sa.Integer(), nullable=False), sa.Column('state', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False), sa.Column('error', sa.Text()),
        sa.Column('message_ids', sa.JSON(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('rule_id', 'ticket_id', 'revision', 'episode', 'occurrence', name='uq_automation_run'))
    op.create_index('ix_automation_runs_rule_id', 'automation_runs', ['rule_id'])
    op.create_index('ix_automation_runs_ticket_id', 'automation_runs', ['ticket_id'])


def downgrade():
    # Reminder-only rules have no target status and cannot be represented by the old engine.
    op.execute('DELETE FROM automation_rules WHERE to_status IS NULL')
    op.drop_table('automation_runs')
    for column in ['revision', 'max_runs', 'repeat_hours', 'actions', 'filters', 'delay_hours']:
        op.drop_column('automation_rules', column)
    op.alter_column('automation_rules', 'to_status', existing_type=sa.String(30), nullable=False)
