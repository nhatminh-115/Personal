"""Integration test proving waiting approval survives complete application restart."""

from pathlib import Path
import aiosqlite
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
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
async def test_waiting_approval_survives_restart(test_db_session, setup_test_workspace: Path, tmp_path: Path):
    checkpoint_db = tmp_path / "durable_checkpoints.db"
    run_id = "restart-durability-run"
    session_id = "restart-durability-sess"
    target_file = setup_test_workspace / "durable_output.txt"

    mem_service = SQLMemoryService(test_db_session)
    appr_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)

    # --- PROCESS LIFECYCLE 1: INITIAL RUN LEADING TO APPROVAL PAUSE ---
    conn1 = await aiosqlite.connect(str(checkpoint_db))
    cp1 = AsyncSqliteSaver(conn1)
    await cp1.setup()
    app1 = build_orchestrator_graph().compile(checkpointer=cp1)

    initial_state: AgentState = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Write persistent test to durable_output.txt",
        "messages": [],
        "retrieved_context": ["User preferences: durable checkpointing"],
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

    res1 = await app1.ainvoke(initial_state, config=config)
    assert "__interrupt__" in res1
    assert not target_file.exists()

    # SIMULATE CRASH / RESTART: Close connection and destroy graph instances
    await conn1.close()
    del app1
    del cp1
    del conn1

    # --- PROCESS LIFECYCLE 2: APPLICATION RESTARTED ---
    # Reconnect from clean state using the same on-disk checkpoint DB
    conn2 = await aiosqlite.connect(str(checkpoint_db))
    cp2 = AsyncSqliteSaver(conn2)
    await cp2.setup()
    app2 = build_orchestrator_graph().compile(checkpointer=cp2)

    # Verify snapshot can be retrieved directly from checkpointer
    saved_snapshot = await app2.aget_state(config)
    assert saved_snapshot is not None
    assert saved_snapshot.values["run_id"] == run_id
    assert saved_snapshot.values["retrieved_context"] == ["User preferences: durable checkpointing"]
    assert len(saved_snapshot.values["tool_requests"]) == 1

    # Resume the SAME graph execution via Command(resume=...)
    res2 = await app2.ainvoke(Command(resume={"decision": "approved"}), config=config)

    assert res2["execution_status"] == RunStatus.COMPLETED.value
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "persistent test"

    await conn2.close()
