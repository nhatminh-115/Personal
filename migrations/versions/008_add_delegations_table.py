"""008_delegations
 
Revision ID: 008_delegations
Revises: 007_add_parent_run_id_to_runs
Create Date: 2026-09-18 15:00:00.000000
 
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "008_delegations"
down_revision: Union[str, None] = "007_add_parent_run_id_to_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "delegations",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "parent_run_id",
            sa.String(length=36),
            sa.ForeignKey("runs.id", name="fk_delegations_parent_run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_tool_call_id", sa.String(length=64), nullable=True),
        sa.Column(
            "child_run_id",
            sa.String(length=36),
            sa.ForeignKey("runs.id", name="fk_delegations_child_run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("specialist_name", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("pending_approval_id", sa.String(length=36), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_delegations_parent_run_id", "delegations", ["parent_run_id"])
    op.create_index("ix_delegations_child_run_id", "delegations", ["child_run_id"])
    op.create_index("ix_delegations_parent_tool_call_id", "delegations", ["parent_tool_call_id"])
    op.create_index("ix_delegations_parent_lookup", "delegations", ["parent_run_id", "parent_tool_call_id"])


def downgrade() -> None:
    op.drop_index("ix_delegations_parent_lookup", table_name="delegations")
    op.drop_index("ix_delegations_parent_tool_call_id", table_name="delegations")
    op.drop_index("ix_delegations_child_run_id", table_name="delegations")
    op.drop_index("ix_delegations_parent_run_id", table_name="delegations")
    op.drop_table("delegations")
