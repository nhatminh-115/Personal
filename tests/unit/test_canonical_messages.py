"""Unit tests for canonical conversation structure and multi-turn tool context."""

from pathlib import Path
import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.db.models import RunStatus
from app.memory.service import SQLMemoryService
from app.models.base import ChatMessage, ModelRequest, ModelRole, ToolCallRequest
from app.models.mock_provider import MockModelProvider
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import build_orchestrator_graph
from app.orchestrator.state import AgentState
from app.tools.registry import tool_registry


@pytest.mark.asyncio
async def test_canonical_message_structure_preservation(test_db_session, setup_test_workspace: Path):
    # Setup sample file
    sample = setup_test_workspace / "data.txt"
    sample.write_text("Canonical Data 123", encoding="utf-8")

    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "test-canonical-run"
    session_id = "test-canonical-sess"

    state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Read data.txt",
        "messages": [],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "execution_status": RunStatus.RUNNING.value,
        "errors": [],
        "final_response": None,
    }

    config = {
        "configurable": {
            "thread_id": run_id,
            "memory_service": mem_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": ModelRouter(),
        }
    }

    res = await app.ainvoke(state, config=config)

    messages = res["messages"]
    assert len(messages) >= 4

    # 1. User message
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Read data.txt"

    # 2. Assistant message with tool_calls
    assert messages[1]["role"] == "assistant"
    assert messages[1].get("tool_calls") is not None
    assert messages[1]["tool_calls"][0]["name"] == "read_workspace_file"

    # 3. Tool message with tool_call_id and result
    assert messages[2]["role"] == "tool"
    assert messages[2]["name"] == "read_workspace_file"
    assert messages[2]["tool_call_id"] == messages[1]["tool_calls"][0]["id"]
    assert "Canonical Data 123" in messages[2]["content"]

    # 4. Final assistant message synthesizing response
    assert messages[3]["role"] == "assistant"
    assert "Canonical Data 123" in messages[3]["content"]


@pytest.mark.asyncio
async def test_multi_turn_tool_context(test_db_session, setup_test_workspace: Path):
    """Test multi-turn tool context preservation across multiple turns in a session."""
    mem_service = SQLMemoryService(test_db_session)
    session_id = "multi-turn-sess"

    # Seed prior turn into working memory
    await mem_service.save_message(session_id, role="user", content="What is my favorite color?")
    await mem_service.save_message(session_id, role="assistant", content="You haven't told me yet.")

    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    state: AgentState = {
        "run_id": "turn-2",
        "session_id": session_id,
        "user_message": "My favorite color is Blue.",
        "messages": [],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "execution_status": RunStatus.RUNNING.value,
        "errors": [],
        "final_response": None,
    }

    config = {
        "configurable": {
            "thread_id": "turn-2",
            "memory_service": mem_service,
            "tool_registry": tool_registry,
            "model_router": ModelRouter(),
        }
    }

    res = await app.ainvoke(state, config=config)

    # History from turn 1 should be loaded in messages
    loaded_msgs = res["messages"]
    assert any(m["content"] == "What is my favorite color?" for m in loaded_msgs)
    assert any(m["content"] == "My favorite color is Blue." for m in loaded_msgs)
