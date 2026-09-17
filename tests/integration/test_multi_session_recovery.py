"""Integration test: Multi-session recovery across application restart.

Verifies:
1. Multiple concurrent sessions (session-A, session-B) can be created and queried independently.
2. Complete application restart recovers all sessions, messages, and state intact.
"""

from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import MessageModel, SessionModel
from app.memory.service import SQLMemoryService


@pytest.mark.asyncio
async def test_multi_session_recovery_across_restart(tmp_path: Path):
    db_file = tmp_path / "persistent_aura.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # --- FIRST APPLICATION LIFECYCLE ---
    engine1 = create_async_engine(db_url)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker1 = async_sessionmaker(engine1, class_=AsyncSession, expire_on_commit=False)

    async with session_maker1() as db1:
        mem1 = SQLMemoryService(db1)

        # Create Session Alpha
        await mem1.get_or_create_session("session-alpha", title="Alpha Project")
        await mem1.save_message("session-alpha", role="user", content="Hello Alpha")
        await mem1.save_message("session-alpha", role="assistant", content="Alpha Ack")
        await mem1.record_episodic_memory("session-alpha", summary="Alpha episode summary")

        # Create Session Beta
        await mem1.get_or_create_session("session-beta", title="Beta Project")
        await mem1.save_message("session-beta", role="user", content="Hello Beta")
        await mem1.save_message("session-beta", role="assistant", content="Beta Ack")

    # SIMULATE APP SHUTDOWN: Dispose all connections
    await engine1.dispose()

    # --- SECOND APPLICATION LIFECYCLE (RESTART) ---
    engine2 = create_async_engine(db_url)
    session_maker2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)

    async with session_maker2() as db2:
        mem2 = SQLMemoryService(db2)

        # 1. Verify Session Alpha recovered
        alpha_session = await mem2.get_or_create_session("session-alpha")
        assert alpha_session.title == "Alpha Project"

        alpha_messages = await mem2.get_session_messages("session-alpha")
        assert len(alpha_messages) == 2
        assert alpha_messages[0].content == "Hello Alpha"
        assert alpha_messages[1].content == "Alpha Ack"

        alpha_episodes = await mem2.get_recent_episodes("session-alpha")
        assert len(alpha_episodes) == 1
        assert "Alpha episode summary" in alpha_episodes[0].content

        # 2. Verify Session Beta recovered independently
        beta_session = await mem2.get_or_create_session("session-beta")
        assert beta_session.title == "Beta Project"

        beta_messages = await mem2.get_session_messages("session-beta")
        assert len(beta_messages) == 2
        assert beta_messages[0].content == "Hello Beta"
        assert beta_messages[1].content == "Beta Ack"

    await engine2.dispose()
