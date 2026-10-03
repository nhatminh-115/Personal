"""Index the remaining paginated memory, approval, and execution reads.

Revision ID: 017_cursor_read_indexes
Revises: 016_keyset_pagination_indexes
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = "017_cursor_read_indexes"
down_revision: Union[str, None] = "016_keyset_pagination_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_memories_created_id", "memories", ["created_at", "id"], unique=False)
    op.create_index(
        "ix_memories_project_created_id", "memories", ["project_name", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_memories_session_created_id", "memories", ["session_id", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_approvals_status_created_id", "approvals", ["status", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_run_events_run_created_id", "run_events", ["run_id", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_events_correlation_occurred_id", "events", ["correlation_id", "occurred_at", "id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_correlation_occurred_id", table_name="events")
    op.drop_index("ix_run_events_run_created_id", table_name="run_events")
    op.drop_index("ix_approvals_status_created_id", table_name="approvals")
    op.drop_index("ix_memories_session_created_id", table_name="memories")
    op.drop_index("ix_memories_project_created_id", table_name="memories")
    op.drop_index("ix_memories_created_id", table_name="memories")
