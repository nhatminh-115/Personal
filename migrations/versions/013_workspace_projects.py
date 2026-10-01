"""Persist user-created project directory entries.

Revision ID: 013_workspace_projects
Revises: 012_workspace_note_links
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013_workspace_projects"
down_revision: Union[str, None] = "012_workspace_note_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("name_key", sa.String(length=128), nullable=False),
        sa.Column("subtitle", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("name_key"),
    )
def downgrade() -> None:
    op.drop_table("workspace_projects")
