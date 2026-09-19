"""009_unique_delegation

Revision ID: 009_unique_delegation
Revises: 008_delegations
Create Date: 2026-09-19 10:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "009_unique_delegation"
down_revision: Union[str, None] = "008_delegations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop existing non-unique lookup index
    op.drop_index("ix_delegations_parent_lookup", table_name="delegations")

    # 2. Create partial unique index on non-null parent_tool_call_id
    op.create_index(
        "uq_delegations_parent_call",
        "delegations",
        ["parent_run_id", "parent_tool_call_id"],
        unique=True,
        postgresql_where=sa.text("parent_tool_call_id IS NOT NULL"),
        sqlite_where=sa.text("parent_tool_call_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_delegations_parent_call", table_name="delegations")
    op.create_index(
        "ix_delegations_parent_lookup",
        "delegations",
        ["parent_run_id", "parent_tool_call_id"],
    )
