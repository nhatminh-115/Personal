"""Unit tests for LangGraph interrupt and resume behavior."""

from pathlib import Path
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.approvals.service import ApprovalService
from app.db.models import RunStatus
from app.memory.service import SQLMemoryService
from app.models.router import model_router
from app.observability.tracer import TraceService
from app.orchestrator.graph import build_orchestrator_graph
from app.orchestrator.state import AgentState
from app.tools.registry import tool_registry


@pytest.mark.asyncio
async def test_interrupt_pause_and_approve(test_db_session, setup_test_workspace: Path):
    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    appr_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "test-interrupt-run"
    session_id = "test-interrupt-sess"
    target_file = setup_test_workspace / "interrupted.txt"

    initial_state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Write hello to interrupted.txt",
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
            "approval_service": appr_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": model_router,
        }
    }

    # 1. First execution turn - should pause at interrupt()
    paused_result = await app.ainvoke(initial_state, config=config)

    assert "__interrupt__" in paused_result
    assert len(paused_result["__interrupt__"]) == 1
    assert not target_file.exists()

    # 2. Resume with approved
    resumed_result = await app.ainvoke(Command(resume={"decision": "approved"}), config=config)

    assert resumed_result["execution_status"] == RunStatus.COMPLETED.value
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_interrupt_pause_and_reject(test_db_session, setup_test_workspace: Path):
    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    appr_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "test-reject-run"
    session_id = "test-reject-sess"
    target_file = setup_test_workspace / "rejected.txt"

    initial_state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Write secret to rejected.txt",
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
            "approval_service": appr_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": model_router,
        }
    }

    await app.ainvoke(initial_state, config=config)
    assert not target_file.exists()

    # Resume with rejected
    resumed_result = await app.ainvoke(
        Command(resume={"decision": "rejected", "decision_notes": "Not allowed"}),
        config=config,
    )

    assert resumed_result["execution_status"] == RunStatus.CANCELLED.value
    assert "rejected by the user" in resumed_result["final_response"]
    assert not target_file.exists()


@pytest.mark.asyncio
async def test_interrupt_pause_and_edit(test_db_session, setup_test_workspace: Path):
    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    appr_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "test-edit-run"
    session_id = "test-edit-sess"
    original_file = setup_test_workspace / "original.txt"
    edited_file = setup_test_workspace / "edited.txt"

    initial_state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Write original to original.txt",
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
            "approval_service": appr_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": model_router,
        }
    }

    await app.ainvoke(initial_state, config=config)

    # User modifies path and content before approving
    resumed_result = await app.ainvoke(
        Command(resume={
            "decision": "edited",
            "edited_input": {"path": "edited.txt", "content": "modified content"},
        }),
        config=config,
    )

    assert resumed_result["execution_status"] == RunStatus.COMPLETED.value
    assert not original_file.exists()
    assert edited_file.exists()
    assert edited_file.read_text(encoding="utf-8") == "modified content"
