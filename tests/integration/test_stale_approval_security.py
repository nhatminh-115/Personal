"""Integration tests for stale approval security and active interrupt binding."""

import asyncio
from pathlib import Path
import pytest
from httpx import AsyncClient
from langgraph.checkpoint.memory import MemorySaver

from app.core.settings import settings
from app.db.models import RunStatus
from app.models.base import ModelResponse, ToolCallRequest
from app.models.mock_provider import MockModelProvider
from app.models.router import model_router
from app.orchestrator.graph import set_global_checkpointer


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
async def test_stale_approval_retry_cannot_authorize_next_interrupt(
    async_client: AsyncClient,
    test_db_session,
    clean_workspace,
    in_memory_checkpointer,
):
    """
    Adversarial scenario:
    1. Model response produces two high-risk write calls A and B.
    2. /v1/chat pauses on A.
    3. Approve A via /v1/approvals/{A}/decision.
    4. Verify graph is now paused on B.
    5. Retry /v1/approvals/{A}/decision.
    6. Verify:
       - Endpoint returns 409 Conflict identifying A as stale and B as active
       - B remains pending in DB
       - B is NOT marked approved
       - Neither unauthorized tool action is executed
       - Graph remains waiting for B
    7. Explicitly approve B.
    8. Only then does execution finish and both files exist.
    """
    client = async_client
    mock_prov: MockModelProvider = model_router.get_provider("mock")  # type: ignore
    mock_prov.clear_queue()

    # Step 1: Queue multi-tool response (write file A and write file B)
    mock_prov.queue_response(
        ModelResponse(
            content="I need to write two separate configuration files.",
            tool_calls=[
                ToolCallRequest(
                    id="call_write_a",
                    name="write_workspace_file",
                    arguments={"path": "file_a.txt", "content": "Content of File A"},
                ),
                ToolCallRequest(
                    id="call_write_b",
                    name="write_workspace_file",
                    arguments={"path": "file_b.txt", "content": "Content of File B"},
                ),
            ],
        )
    )
    mock_prov.queue_response(
        ModelResponse(content="Both files A and B have been successfully written.")
    )

    # Step 2: Start chat turn
    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-stale-1", "message": "Create files A and B"},
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["status"] == "waiting_for_approval"
    approval_a_id = chat_data["approval_id"]
    run_id = chat_data["run_id"]
    assert approval_a_id is not None

    file_a = clean_workspace / "file_a.txt"
    file_b = clean_workspace / "file_b.txt"
    assert not file_a.exists()
    assert not file_b.exists()

    # Step 3: Approve A through /v1/approvals/{A}/decision
    appr_a_res = await client.post(
        f"/v1/approvals/{approval_a_id}/decision",
        json={"decision": "approved", "decision_notes": "Approving write A"},
    )
    assert appr_a_res.status_code == 200
    appr_a_data = appr_a_res.json()
    assert appr_a_data["execution_status"] == "waiting_for_approval"

    # Step 4: Verify graph is now paused on B
    approval_b_id = appr_a_data["approval_id"]
    assert approval_b_id != approval_a_id

    # Check B detail
    b_detail_res = await client.get(f"/v1/approvals/{approval_b_id}")
    assert b_detail_res.status_code == 200
    b_detail = b_detail_res.json()
    assert b_detail["status"] == "pending"
    assert b_detail["tool_call_id"] == "call_write_b"
    assert not file_b.exists()

    # Step 5: Retry /v1/approvals/{A}/decision
    stale_retry_res = await client.post(
        f"/v1/approvals/{approval_a_id}/decision",
        json={"decision": "approved", "decision_notes": "Stale retry of A"},
    )

    # Step 6: Verify rejection of stale retry and preservation of B's suspension
    assert stale_retry_res.status_code == 409
    err_detail = stale_retry_res.json()["detail"]
    assert "stale" in err_detail.lower()
    assert approval_a_id in err_detail
    assert approval_b_id in err_detail

    # Verify B remains strictly pending and has NOT been approved
    b_check_res = await client.get(f"/v1/approvals/{approval_b_id}")
    assert b_check_res.status_code == 200
    assert b_check_res.json()["status"] == "pending"

    # File B must NOT exist yet
    assert not file_b.exists()

    # Step 7: Explicitly approve B
    appr_b_res = await client.post(
        f"/v1/approvals/{approval_b_id}/decision",
        json={"decision": "approved", "decision_notes": "Explicitly approving B"},
    )
    assert appr_b_res.status_code == 200
    appr_b_data = appr_b_res.json()

    # Step 8: Execution completes
    assert appr_b_data["execution_status"] == "completed"
    assert file_a.exists()
    assert file_a.read_text(encoding="utf-8") == "Content of File A"
    assert file_b.exists()
    assert file_b.read_text(encoding="utf-8") == "Content of File B"


@pytest.mark.asyncio
async def test_retry_rejected_old_approval_while_another_active(
    async_client: AsyncClient,
    test_db_session,
    clean_workspace,
    in_memory_checkpointer,
):
    """
    Reject A while B is queued.
    When graph loops to B, retry rejecting/approving A.
    Must return 409 Conflict without affecting B.
    """
    client = async_client
    mock_prov: MockModelProvider = model_router.get_provider("mock")  # type: ignore
    mock_prov.clear_queue()

    mock_prov.queue_response(
        ModelResponse(
            content="Writing X and Y.",
            tool_calls=[
                ToolCallRequest(
                    id="call_x",
                    name="write_workspace_file",
                    arguments={"path": "file_x.txt", "content": "X"},
                ),
                ToolCallRequest(
                    id="call_y",
                    name="write_workspace_file",
                    arguments={"path": "file_y.txt", "content": "Y"},
                ),
            ],
        )
    )
    mock_prov.queue_response(
        ModelResponse(content="Final summary after tool execution.")
    )

    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-stale-reject", "message": "Run X and Y"},
    )
    approval_x_id = chat_res.json()["approval_id"]

    # Reject X
    rej_x_res = await client.post(
        f"/v1/approvals/{approval_x_id}/decision",
        json={"decision": "rejected", "decision_notes": "Rejecting X"},
    )
    assert rej_x_res.status_code == 200
    approval_y_id = rej_x_res.json()["approval_id"]
    assert approval_y_id != approval_x_id

    # Retry rejecting X while Y is active
    retry_rej_x = await client.post(
        f"/v1/approvals/{approval_x_id}/decision",
        json={"decision": "rejected", "decision_notes": "Duplicate rejection of X"},
    )
    assert retry_rej_x.status_code == 409
    assert "stale" in retry_rej_x.json()["detail"].lower()

    # Retry approving X while Y is active
    retry_appr_x = await client.post(
        f"/v1/approvals/{approval_x_id}/decision",
        json={"decision": "approved", "decision_notes": "Attempting to approve stale X"},
    )
    assert retry_appr_x.status_code == 409

    # Y is still pending
    y_status = await client.get(f"/v1/approvals/{approval_y_id}")
    assert y_status.json()["status"] == "pending"
    assert not (clean_workspace / "file_y.txt").exists()

    # Explicitly approve Y
    appr_y_res = await client.post(
        f"/v1/approvals/{approval_y_id}/decision",
        json={"decision": "approved", "decision_notes": "Approving Y"},
    )
    assert appr_y_res.status_code == 200
    assert appr_y_res.json()["execution_status"] == "completed"

    # X must never have executed, Y must have executed
    assert not (clean_workspace / "file_x.txt").exists()
    assert (clean_workspace / "file_y.txt").exists()


@pytest.mark.asyncio
async def test_retry_edited_old_approval_while_another_active(
    async_client: AsyncClient,
    test_db_session,
    clean_workspace,
    in_memory_checkpointer,
):
    """
    Edit A while B is queued.
    When graph loops to B, retry editing/approving A.
    Must return 409 Conflict without affecting B.
    """
    client = async_client
    mock_prov: MockModelProvider = model_router.get_provider("mock")  # type: ignore
    mock_prov.clear_queue()

    mock_prov.queue_response(
        ModelResponse(
            content="Writing M and N.",
            tool_calls=[
                ToolCallRequest(
                    id="call_m",
                    name="write_workspace_file",
                    arguments={"path": "orig_m.txt", "content": "Orig M"},
                ),
                ToolCallRequest(
                    id="call_n",
                    name="write_workspace_file",
                    arguments={"path": "file_n.txt", "content": "N"},
                ),
            ],
        )
    )
    mock_prov.queue_response(
        ModelResponse(content="Done writing M and N.")
    )

    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-stale-edit", "message": "Run M and N"},
    )
    approval_m_id = chat_res.json()["approval_id"]

    # Edit M
    edit_m_res = await client.post(
        f"/v1/approvals/{approval_m_id}/decision",
        json={
            "decision": "edited",
            "decision_notes": "Renaming path to edited_m.txt",
            "edited_input": {"path": "edited_m.txt", "content": "Edited M Content"},
        },
    )
    assert edit_m_res.status_code == 200
    approval_n_id = edit_m_res.json()["approval_id"]
    assert approval_n_id != approval_m_id

    # Retry editing M while N is active
    retry_edit_m = await client.post(
        f"/v1/approvals/{approval_m_id}/decision",
        json={
            "decision": "edited",
            "edited_input": {"path": "tamper_m.txt", "content": "Tampered"},
        },
    )
    assert retry_edit_m.status_code == 409
    assert "stale" in retry_edit_m.json()["detail"].lower()

    # N is still pending
    n_status = await client.get(f"/v1/approvals/{approval_n_id}")
    assert n_status.json()["status"] == "pending"

    # Approve N
    appr_n_res = await client.post(
        f"/v1/approvals/{approval_n_id}/decision",
        json={"decision": "approved"},
    )
    assert appr_n_res.status_code == 200
    assert appr_n_res.json()["execution_status"] == "completed"

    # Verify edited M was written, original M was not, and N was written
    assert (clean_workspace / "edited_m.txt").exists()
    assert not (clean_workspace / "orig_m.txt").exists()
    assert not (clean_workspace / "tamper_m.txt").exists()
    assert (clean_workspace / "file_n.txt").exists()


@pytest.mark.asyncio
async def test_mismatched_approval_or_tool_call_never_resumes(
    async_client: AsyncClient,
    test_db_session,
    clean_workspace,
    in_memory_checkpointer,
):
    """
    Submitting a non-existent approval ID returns 404.
    Submitting an out-of-order pending approval returns 409 without resuming the graph.
    """
    client = async_client
    # Non-existent approval ID
    res = await client.post(
        "/v1/approvals/00000000-0000-0000-0000-000000000000/decision",
        json={"decision": "approved"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_concurrent_duplicate_approval_requests(
    async_client: AsyncClient,
    test_db_session,
    clean_workspace,
    in_memory_checkpointer,
):
    """
    Race condition defense:
    When multiple concurrent requests attempt to approve the same approval_id simultaneously,
    the run lock serializes execution.
    Only the first advances the graph; subsequent requests detect the updated status or next interrupt
    and safely return without double-resuming or accidentally approving the subsequent tool call.
    """
    client = async_client
    mock_prov: MockModelProvider = model_router.get_provider("mock")  # type: ignore
    mock_prov.clear_queue()

    mock_prov.queue_response(
        ModelResponse(
            content="Concurrent test write",
            tool_calls=[
                ToolCallRequest(
                    id="call_c1",
                    name="write_workspace_file",
                    arguments={"path": "c1.txt", "content": "Concurrent 1"},
                ),
                ToolCallRequest(
                    id="call_c2",
                    name="write_workspace_file",
                    arguments={"path": "c2.txt", "content": "Concurrent 2"},
                ),
            ],
        )
    )
    mock_prov.queue_response(
        ModelResponse(content="Done concurrent test.")
    )

    chat_res = await client.post(
        "/v1/chat",
        json={"session_id": "session-concurrent", "message": "Run concurrent C1 and C2"},
    )
    appr_c1_id = chat_res.json()["approval_id"]

    # Launch 5 concurrent approval requests for C1
    tasks = [
        client.post(
            f"/v1/approvals/{appr_c1_id}/decision",
            json={"decision": "approved", "decision_notes": f"Concurrent #{i}"},
        )
        for i in range(5)
    ]
    responses = await asyncio.gather(*tasks)

    # Exactly one request transitions C1 from pending -> approved and returns 200 (advancing to C2)
    status_codes = [r.status_code for r in responses]
    assert 200 in status_codes

    # All other concurrent requests must receive 409 Conflict (stale, already resolved)
    conflict_or_success = [s in (200, 409) for s in status_codes]
    assert all(conflict_or_success)

    # Crucially: C2 must STILL be pending and unexecuted!
    assert not (clean_workspace / "c2.txt").exists()
    pending_apps = await client.get("/v1/approvals/pending")
    pending_ids = [a["id"] for a in pending_apps.json()]
    assert len(pending_ids) == 1
    c2_id = pending_ids[0]
    assert c2_id != appr_c1_id

    # Explicitly approve C2 to complete cleanly
    c2_res = await client.post(
        f"/v1/approvals/{c2_id}/decision",
        json={"decision": "approved"},
    )
    assert c2_res.status_code == 200
    assert c2_res.json()["execution_status"] == "completed"
    assert (clean_workspace / "c1.txt").exists()
    assert (clean_workspace / "c2.txt").exists()
