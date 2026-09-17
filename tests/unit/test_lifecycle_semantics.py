"""Unit tests for run lifecycle transitions, failure categorization, and single terminal events."""

from pathlib import Path
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.approvals.service import ApprovalService
from app.db.models import RunStatus
from app.memory.service import SQLMemoryService
from app.models.router import ModelRouter, model_router
from app.observability.tracer import TraceService
from app.orchestrator.graph import build_orchestrator_graph
from app.orchestrator.state import AgentState
from app.tools.registry import tool_registry


@pytest.mark.asyncio
async def test_lifecycle_single_terminal_event_on_completion(test_db_session, setup_test_workspace: Path):
    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "lifecycle-run-1"
    session_id = "lifecycle-sess-1"

    # Setup sample file
    (setup_test_workspace / "sample.txt").write_text("content", encoding="utf-8")

    state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Read sample.txt",
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
    assert res["execution_status"] == RunStatus.COMPLETED.value

    # Verify events
    events = await trace_service.get_run_events(run_id)
    event_types = [e.event_type for e in events]

    terminal_events = [t for t in event_types if t in {"run_completed", "run_failed", "run_cancelled"}]
    assert len(terminal_events) == 1
    assert terminal_events[0] == "run_completed"


@pytest.mark.asyncio
async def test_lifecycle_single_terminal_event_on_rejection(test_db_session, setup_test_workspace: Path):
    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    appr_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "lifecycle-run-reject"
    session_id = "lifecycle-sess-reject"

    state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Write test to file.txt",
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

    # First turn: paused
    await app.ainvoke(state, config=config)

    # Check approval_requested occurred exactly once so far
    events_step1 = await trace_service.get_run_events(run_id)
    approval_req_events = [e for e in events_step1 if e.event_type == "approval_requested"]
    assert len(approval_req_events) == 1

    # Second turn: reject
    res = await app.ainvoke(Command(resume={"decision": "rejected", "decision_notes": "No"}), config=config)
    assert res["execution_status"] == RunStatus.CANCELLED.value

    # Check terminal events: exactly one terminal event (run_cancelled)
    events_step2 = await trace_service.get_run_events(run_id)
    terminal_events = [e for e in events_step2 if e.event_type in {"run_completed", "run_failed", "run_cancelled"}]
    assert len(terminal_events) == 1
    assert terminal_events[0].event_type == "run_cancelled"


@pytest.mark.asyncio
async def test_failure_categorization_on_tool_error(test_db_session, setup_test_workspace: Path):
    cp = MemorySaver()
    app = build_orchestrator_graph().compile(checkpointer=cp)

    mem_service = SQLMemoryService(test_db_session)
    trace_service = TraceService(test_db_session)

    run_id = "lifecycle-run-fail"
    session_id = "lifecycle-sess-fail"

    # Request reading a file that does not exist
    state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Read non_existent_file.txt",
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

    # Errors should record tool_failure
    assert len(res["errors"]) >= 1
    assert any("tool_failure" in err for err in res["errors"])

    # Tool results should record error_category
    assert res["tool_results"][0]["result"]["error_category"] == "tool_failure"
