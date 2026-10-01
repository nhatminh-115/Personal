"""Add the shared workspace object graph and per-project board layout.

Revision ID: 010_workspace_object_graph
Revises: c98b2edcf21d
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010_workspace_object_graph"
down_revision: Union[str, None] = "c98b2edcf21d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("project_name", sa.String(length=128), nullable=True))
    op.create_index("ix_sessions_project_name", "sessions", ["project_name"], unique=False)

    op.create_table(
        "workspace_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("object_type", sa.String(length=48), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_objects_project_name", "workspace_objects", ["project_name"], unique=False)
    op.create_index("ix_workspace_objects_session_id", "workspace_objects", ["session_id"], unique=False)
    op.create_index("ix_workspace_objects_source_message_id", "workspace_objects", ["source_message_id"], unique=True)
    op.create_index("ix_workspace_objects_object_type", "workspace_objects", ["object_type"], unique=False)

    op.create_table(
        "workspace_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=128), nullable=False),
        sa.Column("source_object_id", sa.String(length=36), nullable=False),
        sa.Column("target_object_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=48), nullable=False),
        sa.Column("edge_family", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_object_id"], ["workspace_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_object_id"], ["workspace_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_edges_project_name", "workspace_edges", ["project_name"], unique=False)
    op.create_index("ix_workspace_edges_source_object_id", "workspace_edges", ["source_object_id"], unique=False)
    op.create_index("ix_workspace_edges_target_object_id", "workspace_edges", ["target_object_id"], unique=False)
    op.create_index("ix_workspace_edges_edge_family", "workspace_edges", ["edge_family"], unique=False)
    op.create_index("ix_workspace_edges_project_family", "workspace_edges", ["project_name", "edge_family"], unique=False)

    op.create_table(
        "workspace_layouts",
        sa.Column("project_name", sa.String(length=128), nullable=False),
        sa.Column("layout_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("project_name"),
    )


def downgrade() -> None:
    op.drop_table("workspace_layouts")
    op.drop_index("ix_workspace_edges_project_family", table_name="workspace_edges")
    op.drop_index("ix_workspace_edges_edge_family", table_name="workspace_edges")
    op.drop_index("ix_workspace_edges_target_object_id", table_name="workspace_edges")
    op.drop_index("ix_workspace_edges_source_object_id", table_name="workspace_edges")
    op.drop_index("ix_workspace_edges_project_name", table_name="workspace_edges")
    op.drop_table("workspace_edges")
    op.drop_index("ix_workspace_objects_object_type", table_name="workspace_objects")
    op.drop_index("ix_workspace_objects_source_message_id", table_name="workspace_objects")
    op.drop_index("ix_workspace_objects_session_id", table_name="workspace_objects")
    op.drop_index("ix_workspace_objects_project_name", table_name="workspace_objects")
    op.drop_table("workspace_objects")
    op.drop_index("ix_sessions_project_name", table_name="sessions")
    op.drop_column("sessions", "project_name")
