"""Durable channel journal and background-worker heartbeats."""
from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "c7d1e9a4b2f0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("request_key", sa.String(96)))
    op.add_column("messages", sa.Column("request_digest", sa.String(64)))
    op.create_index("uq_messages_request_key", "messages", ["request_key"], unique=True)
    op.create_table(
        "channel_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("stream_key", sa.String(128), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("raw_body", sa.LargeBinary()),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="SET NULL")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_key", name="uq_channel_jobs_event_key"),
        sa.UniqueConstraint("message_id", name="uq_channel_jobs_message_id"),
    )
    op.create_index("ix_channel_jobs_ready", "channel_jobs", ["kind", "state", "available_at"])
    op.create_index("ix_channel_jobs_stream", "channel_jobs", ["kind", "stream_key", "id"])
    op.create_index("ix_channel_jobs_ticket_id", "channel_jobs", ["ticket_id"])
    op.create_table(
        "worker_pulses",
        sa.Column("component", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("succeeded_at", sa.DateTime(timezone=True)),
        sa.Column("failed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("expected_interval", sa.Integer(), nullable=False, server_default="60"),
    )


def downgrade():
    op.drop_index("uq_messages_request_key", table_name="messages")
    op.drop_column("messages", "request_digest")
    op.drop_column("messages", "request_key")
    op.drop_table("worker_pulses")
    op.drop_table("channel_jobs")
