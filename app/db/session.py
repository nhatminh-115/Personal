"""Async SQLAlchemy database engine and session factory."""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import settings
from app.db.base import Base


def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Create async SQLAlchemy engine."""
    url = database_url or settings.DATABASE_URL
    return create_async_engine(
        url,
        echo=settings.DATABASE_ECHO,
        future=True,
    )


# Engine & Sessionmaker
engine = get_engine()
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for yielding an async database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db(database_url: str | None = None) -> None:
    """Initialize database tables directly (for SQLite test environments or quickstart)."""
    target_engine = get_engine(database_url) if database_url else engine
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate schema dynamically if tool_call_id column is missing in approvals table
        try:
            await conn.exec_driver_sql("ALTER TABLE approvals ADD COLUMN tool_call_id VARCHAR(64)")
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_approvals_tool_call_id ON approvals (tool_call_id)")
        except Exception:
            pass

        # Migrate memories table dynamically for Phase 2 columns
        for col_def in [
            "embedding_model VARCHAR(64)",
            "embedding_dim INTEGER",
            "project_name VARCHAR(128)",
            "confidence FLOAT DEFAULT 1.0",
            "is_active BOOLEAN DEFAULT 1",
            "supersedes_id VARCHAR(36)",
            "superseded_by_id VARCHAR(36)",
        ]:
            try:
                await conn.exec_driver_sql(f"ALTER TABLE memories ADD COLUMN {col_def}")
            except Exception:
                pass

