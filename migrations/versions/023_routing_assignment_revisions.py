"""Add optimistic revisions to project and session routing assignments."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "023_routing_assignment_revisions"
down_revision: Union[str, None] = "022_automation_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_routing_assignments",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    with op.batch_alter_table("project_routing_assignments") as batch_op:
        batch_op.alter_column("routing_profile_id", existing_type=sa.String(length=36), nullable=True)
    op.add_column(
        "sessions",
        sa.Column("routing_revision", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sessions", "routing_revision")
    with op.batch_alter_table("project_routing_assignments") as batch_op:
        batch_op.alter_column("routing_profile_id", existing_type=sa.String(length=36), nullable=False)
    op.drop_column("project_routing_assignments", "revision")
