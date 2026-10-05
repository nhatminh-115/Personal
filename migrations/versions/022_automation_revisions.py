"""Add optimistic revisions for automation configuration."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "022_automation_revisions"
down_revision: Union[str, None] = "021_workspace_object_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scheduled_jobs",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "revision")
