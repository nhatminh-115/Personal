"""003_pgvector_and_long_term_memory

Revision ID: 003_pgvector_and_long_term_memory
Revises: 002_add_tool_call_id_to_approvals
Create Date: 2026-09-17 17:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = "003_pgvector_and_long_term_memory"
down_revision: Union[str, None] = "002_add_tool_call_id_to_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add new memory metadata and scoping columns
    op.add_column("memories", sa.Column("embedding_model", sa.String(length=64), nullable=True))
    op.add_column("memories", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.add_column("memories", sa.Column("project_name", sa.String(length=128), nullable=True))
    op.add_column("memories", sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"))
    op.add_column("memories", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("memories", sa.Column("supersedes_id", sa.String(length=36), nullable=True))
    op.add_column("memories", sa.Column("superseded_by_id", sa.String(length=36), nullable=True))

    op.create_index("ix_memories_embedding_model", "memories", ["embedding_model"])
    op.create_index("ix_memories_project_name", "memories", ["project_name"])
    op.create_index("ix_memories_is_active", "memories", ["is_active"])

    if is_postgres:
        # Alter embedding column to native pgvector type and create HNSW cosine index
        try:
            op.execute("ALTER TABLE memories ALTER COLUMN embedding TYPE vector(1536) USING embedding::text::vector")
            op.execute("CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw ON memories USING hnsw (embedding vector_cosine_ops)")
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_memories_embedding_hnsw")

    op.drop_index("ix_memories_is_active", table_name="memories")
    op.drop_index("ix_memories_project_name", table_name="memories")
    op.drop_index("ix_memories_embedding_model", table_name="memories")

    op.drop_column("memories", "superseded_by_id")
    op.drop_column("memories", "supersedes_id")
    op.drop_column("memories", "is_active")
    op.drop_column("memories", "confidence")
    op.drop_column("memories", "project_name")
    op.drop_column("memories", "embedding_dim")
    op.drop_column("memories", "embedding_model")
