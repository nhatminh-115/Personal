"""Index paginated routing confirmation reads.

Revision ID: 019_routing_confirm_indexes
Revises: 018_project_automation_indexes
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_routing_confirm_indexes"
down_revision: Union[str, None] = "018_project_automation_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_routing_confirmations_status_created_id",
        "routing_confirmations",
        ["status", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_routing_confirmations_status_session_created_id",
        "routing_confirmations",
        ["status", "session_id", sa.text("created_at DESC"), sa.text("id DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_routing_confirmations_status_session_created_id", table_name="routing_confirmations")
    op.drop_index("ix_routing_confirmations_status_created_id", table_name="routing_confirmations")
