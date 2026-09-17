"""005_event_outbox_hardening

Revision ID: 005_event_outbox_hardening
Revises: 004_event_outbox_and_scheduler
Create Date: 2026-09-17 19:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005_event_outbox_hardening"
down_revision: Union[str, None] = "004_event_outbox_and_scheduler"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add durable outbox columns to events table
    op.add_column("events", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("events", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("events", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("events", sa.Column("locked_by", sa.String(length=64), nullable=True))

    op.create_index("ix_events_idempotency_key", "events", ["idempotency_key"])
    op.create_index("ix_events_next_attempt_at", "events", ["next_attempt_at"])

    # 2. Add lease columns to scheduled_jobs table
    op.add_column("scheduled_jobs", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scheduled_jobs", sa.Column("locked_by", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "locked_by")
    op.drop_column("scheduled_jobs", "locked_at")

    op.drop_index("ix_events_next_attempt_at", table_name="events")
    op.drop_index("ix_events_idempotency_key", table_name="events")

    op.drop_column("events", "locked_by")
    op.drop_column("events", "locked_at")
    op.drop_column("events", "next_attempt_at")
    op.drop_column("events", "max_attempts")
    op.drop_column("events", "idempotency_key")
