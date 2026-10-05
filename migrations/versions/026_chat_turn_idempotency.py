"""Add per-session idempotency keys for chat turns."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026_chat_turn_idempotency"
down_revision: Union[str, None] = "025_memory_active_key_uniqueness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("client_turn_id", sa.String(length=64), nullable=True))
    op.add_column("runs", sa.Column("request_fingerprint", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_runs_session_client_turn",
        "runs",
        ["session_id", "client_turn_id"],
        unique=True,
        sqlite_where=sa.text("client_turn_id IS NOT NULL"),
        postgresql_where=sa.text("client_turn_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_runs_session_client_turn", table_name="runs")
    op.drop_column("runs", "request_fingerprint")
    op.drop_column("runs", "client_turn_id")
