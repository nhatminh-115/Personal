"""Add durable personal workspace notes.

Revision ID: 011_personal_notes
Revises: 010_workspace_object_graph
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_personal_notes"
down_revision: Union[str, None] = "010_workspace_object_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personal_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("project_ids_json", sa.JSON(), nullable=False),
        sa.Column("project_names_json", sa.JSON(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_notes_pinned", "personal_notes", ["pinned"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_personal_notes_pinned", table_name="personal_notes")
    op.drop_table("personal_notes")
