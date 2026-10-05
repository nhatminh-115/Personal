"""Add optimistic revisions to workspace project archive state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "024_workspace_project_revisions"
down_revision: Union[str, None] = "023_routing_assignment_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspace_projects",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("workspace_projects", "revision")
