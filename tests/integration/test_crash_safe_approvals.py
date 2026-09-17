"""Integration tests for crash-safe and idempotent approval resumption."""

from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.api.server import app
from app.approvals.service import ApprovalService
from app.core.settings import settings
from app.db.models import RunModel, RunStatus
from app.models.base import ModelRequest, ModelResponse, ToolCallRequest
from app.models.mock_provider import MockModelProvider
from app.models.router import model_router
from app.orchestrator.graph import get_compiled_graph, set_global_checkpointer


@pytest.fixture
def clean_workspace(tmp_path):
    orig = settings.AURA_WORKSPACE_ROOT
    settings.AURA_WORKSPACE_ROOT = tmp_path
    yield tmp_path
    settings.AURA_WORKSPACE_ROOT = orig


@pytest.fixture
def in_memory_checkpointer():
    cp = MemorySaver()
    set_global_checkpointer(cp)
    yield cp


@pytest.mark.asyncio
async def test_decision_persisted_before_crash_reconciles_on_retry(async_client: AsyncClient, test_db_session, clean_workspace, in_memory_checkpointer):
    """
    Failure window 1:
    The approval decision was committed to the DB, but the process died before graph.ainvoke completed.
    When a client retries or reconciliation occurs, the endpoint detects the existing decision
    and resumes the graph to completion instead of returning 400 Bad Request.
    """
    client = async_client
    # Step 1: Start chat turn requiring write approval
    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-crash-1", "message": "Write Crash Recovery Test to recovered.txt"},
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["status"] == "waiting_for_approval"
    approval_id = chat_data["approval_id"]
    run_id = chat_data["run_id"]

    # Step 2: Simulate crash window: manually record decision in DB (as if step 1 committed and server crashed)
    app_service = ApprovalService(test_db_session)
    await app_service.record_decision(
        approval_id=approval_id,
        decision="approved",
        decision_notes="Simulated pre-crash approval decision",
    )

    # Confirm DB state is already 'approved'
    app_model = await app_service.get_approval(approval_id)
    assert app_model.status == "approved"

    # Step 3: Client retries calling /decision
    retry_res = await client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Client retry after network disconnect"},
    )
    assert retry_res.status_code == 200
    retry_data = retry_res.json()
    assert retry_data["status"] == "approved"
    assert retry_data["execution_status"] == "completed"

    # Verify the tool executed and file was written
    target_file = clean_workspace / "recovered.txt"
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "Crash Recovery Test"


@pytest.mark.asyncio
async def test_duplicate_and_retry_approval_after_completion_is_idempotent(async_client: AsyncClient, test_db_session, clean_workspace, in_memory_checkpointer):
    """
    Failure window 2:
    Client sends duplicate or retry approval request after the run has already finished.
    Must return 200 with the completed run status idempotently, without executing tools twice.
    """
    client = async_client
    # 1. Start turn
    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-idem-1", "message": "Write Idempotent Test to idem.txt"},
    )
    approval_id = chat_res.json()["approval_id"]

    # 2. First approval call
    appr_res1 = await client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "First submission"},
    )
    assert appr_res1.status_code == 200
    data1 = appr_res1.json()
    assert data1["execution_status"] == "completed"

    # 3. Immediate retry / duplicate call
    appr_res2 = await client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Duplicate submission"},
    )
    assert appr_res2.status_code == 200
    data2 = appr_res2.json()
    assert data2["execution_status"] == "completed"
    assert data2["final_response"] == data1["final_response"]


@pytest.mark.asyncio
async def test_provider_failure_during_resume_marks_run_failed_cleanly(async_client: AsyncClient, test_db_session, clean_workspace, in_memory_checkpointer, monkeypatch):
    """
    Failure window 3:
    During resume, model provider raises an unexpected exception (network drop, API 500).
    The system must cleanly transition the run to 'failed', record 'run_failed' trace,
    and return failed status rather than staying stuck in 'waiting_for_approval'.
    """
    client = async_client
    # 1. Start turn
    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-fail-1", "message": "Write Failure Test to fail.txt"},
    )
    approval_id = chat_res.json()["approval_id"]
    run_id = chat_res.json()["run_id"]

    # 2. Mock provider to raise runtime exception when verify_result synthesizes response
    call_count = [0]

    async def failing_route(request: ModelRequest):
        call_count[0] += 1
        raise RuntimeError("LLM provider unavailable: 503 Service Unavailable")

    monkeypatch.setattr(model_router, "route", failing_route)

    # 3. Submit approval
    appr_res = await client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved"},
    )
    assert appr_res.status_code == 200
    data = appr_res.json()
    assert data["execution_status"] == "failed"

    # Check DB run status
    run = await test_db_session.get(RunModel, run_id)
    assert run.status == "failed"
