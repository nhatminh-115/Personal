"""Index automation listings and project execution history.

Revision ID: 018_project_automation_indexes
Revises: 017_cursor_read_indexes
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018_project_automation_indexes"
down_revision: Union[str, None] = "017_cursor_read_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_runs_session_created_id", "runs", ["session_id", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_scheduled_jobs_created_id", "scheduled_jobs",
        [sa.text("created_at DESC"), sa.text("id ASC")], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_jobs_created_id", table_name="scheduled_jobs")
    op.drop_index("ix_runs_session_created_id", table_name="runs")
