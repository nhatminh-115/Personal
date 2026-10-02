"""Persist per-turn privacy metadata with conversation history.

Revision ID: 014_message_privacy_metadata
Revises: 013_workspace_projects
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014_message_privacy_metadata"
down_revision: Union[str, None] = "013_workspace_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "metadata_json",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "metadata_json")
