"""Explicit customer result and acceptance, retaining existing ticket history."""
from alembic import op
import sqlalchemy as sa
revision = 'f319c7d456fb'
down_revision = 'f208b6c345ea'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tickets', sa.Column('resolution_message_id', sa.Integer(), nullable=True))
    op.add_column('tickets', sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_ticket_resolution_message', 'tickets', 'messages', ['resolution_message_id'], ['id'], ondelete='SET NULL')


def downgrade():
    op.drop_constraint('fk_ticket_resolution_message', 'tickets', type_='foreignkey')
    op.drop_column('tickets', 'accepted_at')
    op.drop_column('tickets', 'resolution_message_id')
