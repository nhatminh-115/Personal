"""007_add_parent_run_id_to_runs

Revision ID: 007_add_parent_run_id_to_runs
Revises: 006_unique_idempotency_key
Create Date: 2026-09-18 13:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007_add_parent_run_id_to_runs"
down_revision: Union[str, None] = "006_unique_idempotency_key"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "parent_run_id",
                sa.String(36),
                sa.ForeignKey("runs.id", name="fk_runs_parent_run_id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_runs_parent_run_id", ["parent_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_index("ix_runs_parent_run_id")
        batch_op.drop_constraint("fk_runs_parent_run_id", type_="foreignkey")
        batch_op.drop_column("parent_run_id")


