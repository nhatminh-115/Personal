"""Add personal workspace note links into project graphs.

Revision ID: 012_workspace_note_links
Revises: 011_unique_route_default
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_workspace_note_links"
down_revision: Union[str, None] = "011_unique_route_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_objects") as batch_op:
        batch_op.alter_column(
            "project_name",
            existing_type=sa.String(length=128),
            nullable=True,
        )
    op.create_table(
        "workspace_object_project_links",
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["object_id"], ["workspace_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("object_id", "project_name"),
    )
    op.create_index(
        "ix_workspace_object_project_links_project",
        "workspace_object_project_links",
        ["project_name"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    personal_note_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM workspace_objects WHERE project_name IS NULL")
    ).scalar_one()
    if personal_note_count:
        raise RuntimeError("Cannot downgrade while personal workspace notes exist; export or link them to a project first.")
    op.drop_index(
        "ix_workspace_object_project_links_project",
        table_name="workspace_object_project_links",
    )
    op.drop_table("workspace_object_project_links")
    with op.batch_alter_table("workspace_objects") as batch_op:
        batch_op.alter_column(
            "project_name",
            existing_type=sa.String(length=128),
            nullable=False,
        )
