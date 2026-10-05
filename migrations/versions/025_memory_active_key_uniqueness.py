"""Enforce one active project/profile memory per key."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_memory_active_key_uniqueness"
down_revision: Union[str, None] = "024_workspace_project_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_duplicate_active_memories() -> None:
    memories = sa.table(
        "memories",
        sa.column("id", sa.String(36)),
        sa.column("memory_type", sa.String(32)),
        sa.column("project_name", sa.String(128)),
        sa.column("key", sa.String(255)),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("superseded_by_id", sa.String(36)),
    )
    connection = op.get_bind()
    duplicate_groups = connection.execute(
        sa.select(
            memories.c.memory_type,
            memories.c.project_name,
            memories.c.key,
        )
        .where(
            memories.c.memory_type.in_(("project", "profile")),
            memories.c.is_active.is_(True),
            memories.c.key.is_not(None),
            sa.or_(
                memories.c.memory_type == "project",
                sa.and_(memories.c.memory_type == "profile", memories.c.project_name.is_(None)),
            ),
        )
        .group_by(memories.c.memory_type, memories.c.project_name, memories.c.key)
        .having(sa.func.count() > 1)
    ).all()

    for memory_type, project_name, key in duplicate_groups:
        scope = memories.c.project_name.is_(None) if project_name is None else memories.c.project_name == project_name
        matching = connection.execute(
            sa.select(memories.c.id)
            .where(
                memories.c.memory_type == memory_type,
                scope,
                memories.c.key == key,
                memories.c.is_active.is_(True),
            )
            .order_by(memories.c.created_at.desc(), memories.c.id.desc())
        ).scalars().all()
        if not matching:
            continue
        connection.execute(
            sa.update(memories)
            .where(memories.c.id.in_(matching[1:]))
            .values(
                is_active=False,
                superseded_by_id=sa.func.coalesce(memories.c.superseded_by_id, matching[0]),
            )
        )


def upgrade() -> None:
    # Keep all prior content and provenance; for historical duplicate active
    # versions, retain the newest as active and connect older rows to it.
    _normalize_duplicate_active_memories()
    op.create_index(
        "uq_memories_active_project_key",
        "memories",
        [sa.text("coalesce(project_name, '')"), "key"],
        unique=True,
        sqlite_where=sa.text("memory_type = 'project' AND is_active = 1 AND key IS NOT NULL"),
        postgresql_where=sa.text("memory_type = 'project' AND is_active IS TRUE AND key IS NOT NULL"),
    )
    op.create_index(
        "uq_memories_active_profile_key",
        "memories",
        ["key"],
        unique=True,
        sqlite_where=sa.text("memory_type = 'profile' AND project_name IS NULL AND is_active = 1 AND key IS NOT NULL"),
        postgresql_where=sa.text("memory_type = 'profile' AND project_name IS NULL AND is_active IS TRUE AND key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_memories_active_profile_key", table_name="memories")
    op.drop_index("uq_memories_active_project_key", table_name="memories")
