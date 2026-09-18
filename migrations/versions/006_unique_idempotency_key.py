"""006_unique_idempotency_key

Revision ID: 006_unique_idempotency_key
Revises: 005_event_outbox_hardening
Create Date: 2026-09-18 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006_unique_idempotency_key"
down_revision: Union[str, None] = "005_event_outbox_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop old non-unique index
    op.drop_index("ix_events_idempotency_key", table_name="events")

    # 2. Create partial unique index on non-null idempotency_key
    op.create_index(
        "uq_events_idempotency_key",
        "events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_events_idempotency_key", table_name="events")
    op.create_index("ix_events_idempotency_key", "events", ["idempotency_key"])
