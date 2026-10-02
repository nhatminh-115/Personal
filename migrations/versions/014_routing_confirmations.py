"""Persist ask-before-cloud routing confirmations.

Revision ID: 014_routing_confirmations
Revises: 013_workspace_projects
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014_routing_confirmations"
down_revision: Union[str, None] = "013_workspace_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "routing_confirmations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("root_run_id", sa.String(length=36), nullable=False),
        sa.Column("execution_run_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("proposed_provider", sa.String(length=128), nullable=False),
        sa.Column("proposed_model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["root_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_routing_confirmations_root_run_id", "routing_confirmations", ["root_run_id"])
    op.create_index("ix_routing_confirmations_execution_run_id", "routing_confirmations", ["execution_run_id"])
    op.create_index("ix_routing_confirmations_session_id", "routing_confirmations", ["session_id"])
    op.create_index("ix_routing_confirmations_status", "routing_confirmations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_routing_confirmations_status", table_name="routing_confirmations")
    op.drop_index("ix_routing_confirmations_session_id", table_name="routing_confirmations")
    op.drop_index("ix_routing_confirmations_execution_run_id", table_name="routing_confirmations")
    op.drop_index("ix_routing_confirmations_root_run_id", table_name="routing_confirmations")
    op.drop_table("routing_confirmations")
