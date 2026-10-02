import pytest

from app.db.models import RunStatus
from app.memory.context import ContextAssembler
from app.memory.service import SQLMemoryService
from app.orchestrator.nodes import update_memory_node


@pytest.mark.asyncio
async def test_runtime_episode_preserves_local_only_privacy_when_reassembled(test_db_session):
    memory_service = SQLMemoryService(db=test_db_session)
    state = {
        "run_id": "private-episode-run",
        "session_id": "private-episode-session",
        "user_message": "What is 2 + 2?",
        "final_response": "4",
        "execution_status": RunStatus.COMPLETED.value,
        "tool_results": [{"name": "workspace.inspect"}],
        "metadata": {
            "routing_context_dict": {
                "privacy_requirement": "local_only",
            },
        },
    }

    await update_memory_node(
        state,
        {"configurable": {"memory_service": memory_service}},
    )

    episodes = await memory_service.get_recent_episodes(session_id=state["session_id"])
    assert len(episodes) == 1
    assert episodes[0].metadata_json["privacy_policy"] == "local_only"

    assembled = await ContextAssembler(memory_service).assemble_context(
        session_id=state["session_id"],
        user_message="",
    )
    assert assembled.episodes == [episodes[0].content]
    assert assembled.privacy_requirement == "local_only"
    assert {
        "memory_id": episodes[0].id,
        "privacy_policy": "local_only",
    } in assembled.privacy_memory_sources


@pytest.mark.asyncio
async def test_runtime_episode_with_unknown_privacy_classification_is_not_persisted(test_db_session):
    memory_service = SQLMemoryService(db=test_db_session)
    state = {
        "run_id": "unknown-privacy-episode-run",
        "session_id": "unknown-privacy-episode-session",
        "user_message": "What is 2 + 2?",
        "final_response": "4",
        "execution_status": RunStatus.COMPLETED.value,
        "tool_results": [{"name": "workspace.inspect"}],
        "metadata": {
            "routing_context_dict": {
                "privacy_requirement": "secret-but-unsupported",
            },
        },
    }

    await update_memory_node(
        state,
        {"configurable": {"memory_service": memory_service}},
    )

    assert await memory_service.get_recent_episodes(session_id=state["session_id"]) == []
