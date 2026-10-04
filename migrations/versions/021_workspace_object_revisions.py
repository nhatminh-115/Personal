"""Add optimistic revision tracking to workspace objects.

Revision ID: 021_workspace_object_revisions
Revises: 020_workspace_project_archiving
Create Date: 2026-10-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "021_workspace_object_revisions"
down_revision: Union[str, None] = "020_workspace_project_archiving"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspace_objects",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("workspace_objects", "revision")
