"""Customer bot reply context for text, files and status notifications."""
from alembic import op
import sqlalchemy as sa
revision = 'f208b6c345ea'
down_revision = 'e1f7a5b234d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('messenger_replies', sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('channel', sa.String(20), nullable=False), sa.Column('account', sa.String(20), nullable=False),
        sa.Column('chat_id', sa.String(128), nullable=False), sa.Column('external_message_id', sa.String(128), nullable=False),
        sa.Column('ticket_id', sa.Integer(), sa.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contact_id', sa.Integer(), sa.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('message_id', sa.Integer(), sa.ForeignKey('messages.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('channel', 'account', 'chat_id', 'external_message_id', name='uq_messenger_reply'))
    op.create_index('ix_messenger_replies_ticket_id', 'messenger_replies', ['ticket_id'])


def downgrade():
    op.drop_table('messenger_replies')
