"""Persist cooperative run cancellation requests."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027_durable_run_cancellation"
down_revision: Union[str, None] = "026_chat_turn_idempotency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "cancel_requested_at")
