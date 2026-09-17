"""Unit tests for the MemoryService multi-tier subsystem."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory.service import SQLMemoryService


@pytest.mark.asyncio
async def test_session_lifecycle(test_db_session: AsyncSession):
    mem_service = SQLMemoryService(test_db_session)

    # 1. Create session
    session = await mem_service.get_or_create_session("sess-1", title="Test Session")
    assert session.id == "sess-1"
    assert session.title == "Test Session"

    # 2. Re-fetching existing session returns same record
    session_again = await mem_service.get_or_create_session("sess-1")
    assert session_again.id == "sess-1"


@pytest.mark.asyncio
async def test_working_memory_messages(test_db_session: AsyncSession):
    mem_service = SQLMemoryService(test_db_session)
    session_id = "sess-msg"

    await mem_service.save_message(session_id, role="user", content="Hello!")
    await mem_service.save_message(session_id, role="assistant", content="Hi there!")

    messages = await mem_service.get_session_messages(session_id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello!"
    assert messages[1].role == "assistant"
    assert messages[1].content == "Hi there!"


@pytest.mark.asyncio
async def test_episodic_memory(test_db_session: AsyncSession):
    mem_service = SQLMemoryService(test_db_session)
    session_id = "sess-epi"

    await mem_service.record_episodic_memory(
        session_id=session_id,
        summary="User instructed to organize receipts.",
        metadata={"milestone": "step_1"},
    )

    episodes = await mem_service.get_recent_episodes(session_id=session_id)
    assert len(episodes) == 1
    assert "organize receipts" in episodes[0].content


@pytest.mark.asyncio
async def test_profile_memory(test_db_session: AsyncSession):
    mem_service = SQLMemoryService(test_db_session)

    await mem_service.set_profile_fact("preferred_language", "Vietnamese")
    fact = await mem_service.get_profile_fact("preferred_language")
    assert fact == "Vietnamese"

    # Update fact
    await mem_service.set_profile_fact("preferred_language", "English")
    fact_updated = await mem_service.get_profile_fact("preferred_language")
    assert fact_updated == "English"
