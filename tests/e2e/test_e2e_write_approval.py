"""E2E Test: Human-in-the-loop approval pause and resume flow (Write File).

Flow:
user: "Write hello world to result.txt"
Expected:
* orchestrator requests filesystem write
* execution pauses
* approval object is created
* file DOES NOT exist yet
* approval is granted
* run resumes
* file is written
* run completes
"""

from pathlib import Path
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_e2e_write_approval_and_resume_flow(async_client: AsyncClient, setup_test_workspace: Path):
    session_id = "e2e-write-sess-1"
    target_file = setup_test_workspace / "result.txt"

    # Verify file definitely does not exist initially
    assert not target_file.exists()

    # 1. User requests file write
    chat_resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Write hello world to result.txt"},
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()

    # Verify execution was PAUSED awaiting approval
    assert chat_data["status"] == "waiting_for_approval"
    approval_id = chat_data["approval_id"]
    assert approval_id is not None

    # CRITICAL CHECK: File MUST NOT exist yet while paused
    assert not target_file.exists(), "Security invariant violation: File was written before human approval!"

    # 2. Inspect pending approvals via API
    pending_resp = await async_client.get("/v1/approvals/pending")
    assert pending_resp.status_code == 200
    pending_list = pending_resp.json()
    assert any(a["id"] == approval_id for a in pending_list)

    # 3. User grants approval
    decision_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Permission granted by user."},
    )
    assert decision_resp.status_code == 200
    decision_data = decision_resp.json()

    assert decision_data["status"] == "approved"
    assert decision_data["execution_status"] == "completed"

    # 4. Verify file now exists with the exact written content
    assert target_file.exists()
    assert target_file.read_text(encoding="utf-8") == "hello world"

    # 5. Verify run trace recorded approval requested and granted
    run_id = decision_data["run_id"]
    run_resp = await async_client.get(f"/v1/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()

    event_types = [e["event_type"] for e in run_data["events"]]
    assert "approval_requested" in event_types
    assert "approval_granted" in event_types
    assert "tool_executed" in event_types
    assert "run_completed" in event_types
