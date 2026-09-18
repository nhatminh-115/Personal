"""Pytest test configuration and fixtures."""

import os
import shutil
from pathlib import Path
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.server import app
from app.core.settings import settings
from app.db.base import Base
from app.db.session import get_db
from app.models.mock_provider import MockModelProvider
from app.models.router import model_router


from langgraph.checkpoint.memory import MemorySaver
from app.orchestrator.graph import set_global_checkpointer


@pytest.fixture(autouse=True)
def setup_test_checkpointer():
    """Ensure a fresh, isolated MemorySaver checkpointer for every test."""
    cp = MemorySaver()
    set_global_checkpointer(cp)
    yield cp


@pytest.fixture(autouse=True)
def reset_mock_model_provider():
    """Ensure the mock model provider queue and call history are cleared for every test."""
    mock = model_router.get_provider("mock")
    if isinstance(mock, MockModelProvider):
        mock.clear_queue()
        mock.call_history.clear()
    yield
    if isinstance(mock, MockModelProvider):
        mock.clear_queue()
        mock.call_history.clear()


@pytest.fixture(autouse=True)
def setup_test_workspace(tmp_path: Path):
    """Ensure a clean, isolated temporary workspace for every test."""
    test_workspace = tmp_path / "workspace"
    test_workspace.mkdir(parents=True, exist_ok=True)
    original_root = settings.AURA_WORKSPACE_ROOT
    settings.AURA_WORKSPACE_ROOT = test_workspace
    yield test_workspace
    settings.AURA_WORKSPACE_ROOT = original_root


@pytest_asyncio.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated, transactional in-memory SQLite database session."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def async_client(test_db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTP async test client with database dependency override."""
    async def override_get_db():
        yield test_db_session

    app.dependency_overrides[get_db] = override_get_db

    # Ensure mock provider is configured for testing
    settings.MODEL_PROVIDER = "mock"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
