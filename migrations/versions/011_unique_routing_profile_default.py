"""Enforce a single custom routing default.

Revision ID: 011_unique_routing_profile_default
Revises: 010_workspace_object_graph
Create Date: 2026-10-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011_unique_routing_profile_default"
down_revision: Union[str, None] = "010_workspace_object_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    # Older deployments could contain multiple defaults. Preserve the most
    # recently updated profile, with stable tie breakers, before adding the
    # constraint so upgrades remain safe for existing data.
    winner_id = connection.execute(
        sa.text(
            "SELECT id FROM routing_profiles WHERE is_default = TRUE "
            "ORDER BY updated_at DESC, created_at DESC, id DESC LIMIT 1"
        )
    ).scalar_one_or_none()
    connection.execute(sa.text("UPDATE routing_profiles SET is_default = FALSE"))
    if winner_id is not None:
        connection.execute(
            sa.text("UPDATE routing_profiles SET is_default = TRUE WHERE id = :profile_id"),
            {"profile_id": winner_id},
        )

    op.create_index(
        "uq_routing_profiles_single_default",
        "routing_profiles",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default IS TRUE"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade() -> None:
    op.drop_index("uq_routing_profiles_single_default", table_name="routing_profiles")
