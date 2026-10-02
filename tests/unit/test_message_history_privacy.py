import pytest

from app.core.errors import ContextSelectionError
from app.db.models import RunStatus
from app.memory.context import ContextAssembler
from app.memory.service import SQLMemoryService
from app.orchestrator.nodes import load_context_node, update_memory_node


@pytest.mark.asyncio
async def test_runtime_turn_privacy_survives_persistence_and_constrains_next_route(test_db_session):
    memory_service = SQLMemoryService(db=test_db_session)
    completed_turn = {
        "run_id": "history-privacy-run",
        "session_id": "history-privacy-session",
        "user_message": "What is 2 + 2?",
        "final_response": "4",
        "execution_status": RunStatus.COMPLETED.value,
        "tool_results": [],
        "metadata": {
            "routing_context_dict": {
                "privacy_requirement": "local_only",
            },
        },
    }

    await update_memory_node(
        completed_turn,
        {"configurable": {"memory_service": memory_service}},
    )

    history = await memory_service.get_session_messages(completed_turn["session_id"])
    assert [message.metadata_json["privacy_policy"] for message in history] == [
        "local_only",
        "local_only",
    ]

    next_turn = {
        "run_id": "history-privacy-next-run",
        "session_id": completed_turn["session_id"],
        "user_message": "Continue.",
        "messages": [],
        "metadata": {
            "routing_context_dict": {
                "privacy_requirement": "public",
            },
        },
    }
    loaded = await load_context_node(
        next_turn,
        {"configurable": {"memory_service": memory_service}},
    )

    assert loaded["metadata"]["routing_context_dict"]["privacy_requirement"] == "local_only"
    assert [message["content"] for message in loaded["messages"][:2]] == [
        "What is 2 + 2?",
        "4",
    ]


@pytest.mark.asyncio
async def test_unsupported_history_privacy_classification_fails_closed(test_db_session):
    memory_service = SQLMemoryService(db=test_db_session)
    await memory_service.save_message(
        "unknown-history-privacy-session",
        role="user",
        content="Classified history",
        metadata={"privacy_policy": "secret-but-unsupported"},
    )

    with pytest.raises(ContextSelectionError, match="unsupported privacy classification"):
        await ContextAssembler(memory_service).assemble_context(
            session_id="unknown-history-privacy-session",
            user_message="Continue.",
        )
