"""Add reversible archive state to durable workspace projects.

Revision ID: 020_workspace_project_archiving
Revises: 019_routing_confirm_indexes
Create Date: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_workspace_project_archiving"
down_revision: Union[str, None] = "019_routing_confirm_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workspace_projects", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_workspace_projects_archived_created_id",
        "workspace_projects",
        ["archived_at", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_projects_archived_created_id", table_name="workspace_projects")
    op.drop_column("workspace_projects", "archived_at")
