import pytest

from app.memory.context import ContextAssembler
from app.memory.service import SQLMemoryService


@pytest.mark.asyncio
async def test_unclassified_legacy_history_and_episodes_are_local_only(test_db_session):
    memory_service = SQLMemoryService(db=test_db_session)
    session_id = "unclassified-legacy-session"
    message = await memory_service.save_message(
        session_id,
        role="assistant",
        content="A response from before privacy metadata was persisted.",
    )
    episode = await memory_service.record_episodic_memory(
        session_id,
        summary="A legacy interaction with no recorded privacy policy.",
    )

    assembled = await ContextAssembler(memory_service).assemble_context(
        session_id=session_id,
        user_message="Continue the conversation.",
    )

    assert assembled.privacy_requirement == "local_only"
    assert {source["memory_id"] for source in assembled.privacy_memory_sources} == {
        message.id,
        episode.id,
    }
    assert all(source["privacy_policy"] == "local_only" for source in assembled.privacy_memory_sources)
