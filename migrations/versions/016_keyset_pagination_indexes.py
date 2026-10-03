"""Add indexes for keyset-paginated workspace and conversation reads.

Revision ID: 016_keyset_pagination_indexes
Revises: 015_routing_confirmations
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_keyset_pagination_indexes"
down_revision: Union[str, None] = "015_routing_confirmations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_sessions_updated_id", "sessions", ["updated_at", "id"], unique=False,
    )
    op.create_index(
        "ix_sessions_project_updated_id", "sessions", ["project_name", "updated_at", "id"], unique=False,
    )
    op.create_index(
        "ix_messages_session_created_id", "messages", ["session_id", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_workspace_projects_created_id", "workspace_projects", ["created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_workspace_objects_project_created_id", "workspace_objects", ["project_name", "created_at", "id"], unique=False,
    )
    op.create_index(
        "ix_workspace_objects_personal_updated_id",
        "workspace_objects",
        ["project_name", "object_type", "created_by", sa.text("updated_at DESC"), sa.text("id ASC")],
        unique=False,
    )
    op.create_index(
        "ix_workspace_objects_personal_created_id",
        "workspace_objects",
        ["project_name", "object_type", "created_by", sa.text("created_at DESC"), sa.text("id ASC")],
        unique=False,
    )
    op.create_index(
        "ix_workspace_objects_personal_card_created_id",
        "workspace_objects",
        ["project_name", "object_type", "created_by", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_edges_project_created_id", "workspace_edges", ["project_name", "created_at", "id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_edges_project_created_id", table_name="workspace_edges")
    op.drop_index("ix_workspace_objects_personal_card_created_id", table_name="workspace_objects")
    op.drop_index("ix_workspace_objects_personal_created_id", table_name="workspace_objects")
    op.drop_index("ix_workspace_objects_personal_updated_id", table_name="workspace_objects")
    op.drop_index("ix_workspace_objects_project_created_id", table_name="workspace_objects")
    op.drop_index("ix_workspace_projects_created_id", table_name="workspace_projects")
    op.drop_index("ix_messages_session_created_id", table_name="messages")
    op.drop_index("ix_sessions_project_updated_id", table_name="sessions")
    op.drop_index("ix_sessions_updated_id", table_name="sessions")
