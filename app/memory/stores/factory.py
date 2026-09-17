"""Factory for instantiating the appropriate SemanticMemoryStore based on active database dialect."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.memory.stores.base import SemanticMemoryStore
from app.memory.stores.pgvector_store import PgVectorSemanticStore
from app.memory.stores.sqlite_store import SqliteSemanticStore


def get_semantic_store(db: AsyncSession) -> SemanticMemoryStore:
    """Return dialect-specific vector memory store (PgVectorSemanticStore or SqliteSemanticStore)."""
    dialect_name = ""
    if db.bind is not None:
        dialect_name = getattr(db.bind.dialect, "name", "")

    if dialect_name == "postgresql":
        return PgVectorSemanticStore(db)
    return SqliteSemanticStore(db)


create_semantic_store = get_semantic_store

