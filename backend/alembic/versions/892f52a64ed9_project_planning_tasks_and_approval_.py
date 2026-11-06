"""project planning tasks and approval rounds

Revision ID: 892f52a64ed9
Revises: e6f7a8b9c0d1
Create Date: 2026-11-06 10:37:17.272112

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '892f52a64ed9'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('work_projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=True),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('approval_round', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('draft','planning','approval','approved','in_progress','paused','completed','cancelled')", name='ck_work_project_status'),
    sa.CheckConstraint('due_date IS NULL OR start_date IS NULL OR due_date >= start_date', name='ck_work_project_dates'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_projects_organization_id'), 'work_projects', ['organization_id'], unique=False)
    op.create_index(op.f('ix_work_projects_owner_id'), 'work_projects', ['owner_id'], unique=False)
    op.create_index('ix_work_projects_status_due', 'work_projects', ['status', 'due_date'], unique=False)
    op.create_table('work_approvals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('round', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('approver_name', sa.String(length=255), nullable=False),
    sa.Column('state', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('comment', sa.Text(), server_default='', nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("state IN ('pending','approved','rejected','superseded')", name='ck_work_approval_state'),
    sa.CheckConstraint('(user_id IS NULL) != (contact_id IS NULL)', name='ck_work_approval_actor'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['work_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'round', 'contact_id', name='uq_work_approval_contact'),
    sa.UniqueConstraint('project_id', 'round', 'user_id', name='uq_work_approval_user')
    )
    op.create_index(op.f('ix_work_approvals_contact_id'), 'work_approvals', ['contact_id'], unique=False)
    op.create_index(op.f('ix_work_approvals_project_id'), 'work_approvals', ['project_id'], unique=False)
    op.create_index(op.f('ix_work_approvals_user_id'), 'work_approvals', ['user_id'], unique=False)
    op.create_table('work_comments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['work_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_comments_project_id'), 'work_comments', ['project_id'], unique=False)
    op.create_table('work_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('stage', sa.String(length=100), server_default='Основной этап', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='backlog', nullable=False),
    sa.Column('assignee_id', sa.Integer(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('estimate_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('actual_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('completion_note', sa.Text(), server_default='', nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('backlog','ready','in_progress','review','done','cancelled')", name='ck_work_task_status'),
    sa.CheckConstraint('due_date IS NULL OR start_date IS NULL OR due_date >= start_date', name='ck_work_task_dates'),
    sa.CheckConstraint('estimate_minutes >= 0 AND actual_minutes >= 0', name='ck_work_task_minutes'),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['work_projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_tasks_assignee_id'), 'work_tasks', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_work_tasks_project_id'), 'work_tasks', ['project_id'], unique=False)
    op.create_table('work_dependencies',
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('depends_on_id', sa.Integer(), nullable=False),
    sa.CheckConstraint('task_id != depends_on_id', name='ck_work_dependency_self'),
    sa.ForeignKeyConstraint(['depends_on_id'], ['work_tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['work_tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('task_id', 'depends_on_id')
    )
    op.create_table('work_ticket_links',
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['work_projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('project_id', 'ticket_id')
    )
    op.add_column('notifications', sa.Column('project_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_notifications_project_id'), 'notifications', ['project_id'], unique=False)
    op.create_foreign_key('notifications_project_id_fkey', 'notifications', 'work_projects', ['project_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    op.drop_constraint('notifications_project_id_fkey', 'notifications', type_='foreignkey')
    op.drop_index(op.f('ix_notifications_project_id'), table_name='notifications')
    op.drop_column('notifications', 'project_id')
    op.drop_table('work_ticket_links')
    op.drop_table('work_dependencies')
    op.drop_index(op.f('ix_work_tasks_project_id'), table_name='work_tasks')
    op.drop_index(op.f('ix_work_tasks_assignee_id'), table_name='work_tasks')
    op.drop_table('work_tasks')
    op.drop_index(op.f('ix_work_comments_project_id'), table_name='work_comments')
    op.drop_table('work_comments')
    op.drop_index(op.f('ix_work_approvals_user_id'), table_name='work_approvals')
    op.drop_index(op.f('ix_work_approvals_project_id'), table_name='work_approvals')
    op.drop_index(op.f('ix_work_approvals_contact_id'), table_name='work_approvals')
    op.drop_table('work_approvals')
    op.drop_index('ix_work_projects_status_due', table_name='work_projects')
    op.drop_index(op.f('ix_work_projects_owner_id'), table_name='work_projects')
    op.drop_index(op.f('ix_work_projects_organization_id'), table_name='work_projects')
    op.drop_table('work_projects')
