"""Persist focused Study sessions.

Revision ID: 012_study_sessions
Revises: 011_personal_notes
Create Date: 2026-10-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "012_study_sessions"
down_revision: Union[str, None] = "011_personal_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("track_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_study_sessions_track_id", "study_sessions", ["track_id"], unique=False)
    op.create_index("ix_study_sessions_status", "study_sessions", ["status"], unique=False)
    op.create_index(
        "uq_study_sessions_single_active",
        "study_sessions",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_study_sessions_single_active", table_name="study_sessions")
    op.drop_index("ix_study_sessions_status", table_name="study_sessions")
    op.drop_index("ix_study_sessions_track_id", table_name="study_sessions")
    op.drop_table("study_sessions")
