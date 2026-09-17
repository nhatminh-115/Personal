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
