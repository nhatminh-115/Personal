"""002_add_tool_call_id_to_approvals

Revision ID: 002_add_tool_call_id
Revises: 001_initial_schema
Create Date: 2026-09-17 14:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_add_tool_call_id"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("approvals", sa.Column("tool_call_id", sa.String(length=64), nullable=True))
    op.create_index("ix_approvals_tool_call_id", "approvals", ["tool_call_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_tool_call_id", table_name="approvals")
    op.drop_column("approvals", "tool_call_id")
