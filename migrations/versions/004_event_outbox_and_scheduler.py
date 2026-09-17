"""004_event_outbox_and_scheduler

Revision ID: 004_event_outbox_and_scheduler
Revises: 003_pgvector_memory
Create Date: 2026-09-17 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_event_outbox_and_scheduler"
down_revision: Union[str, None] = "003_pgvector_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create events table
    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="system"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index("ix_events_correlation_id", "events", ["correlation_id"])

    # 2. Create scheduled_jobs table
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False, server_default="one_shot"),
        sa.Column("schedule_expression", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_scheduled_jobs_is_active", "scheduled_jobs", ["is_active"])
    op.create_index("ix_scheduled_jobs_next_run_at", "scheduled_jobs", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_jobs_next_run_at", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_is_active", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")

    op.drop_index("ix_events_correlation_id", table_name="events")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_table("events")
