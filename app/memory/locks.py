"""Database-scoped locks for mutations of one durable memory key."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def project_memory_lock_key(project_name: str, key: str | None) -> str:
    key = key or ""
    prefix = f"{project_name}:"
    return key if key.startswith(prefix) else f"{prefix}{key}"


async def lock_memory_key(
    db: AsyncSession,
    *,
    memory_type: str,
    project_name: str | None,
    key: str,
) -> None:
    """Serialize active-version changes for one key on PostgreSQL.

    SQLite serializes writes at the database level. PostgreSQL uses a
    transaction advisory lock; partial unique indexes remain the final guard.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    lock_key = f"aura:memory-key:{memory_type}:{project_name or ''}:{key}"
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": lock_key},
    )
