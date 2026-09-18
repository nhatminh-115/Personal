"""Integration tests for Milestone 3A: Iterative Agent Execution Loop & Bounded Controls."""

import time
import pytest
from httpx import AsyncClient
from pathlib import Path

from app.models.base import ModelResponse, ToolCallRequest
from app.models.router import model_router
from app.models.mock_provider import MockModelProvider


@pytest.mark.asyncio
async def test_multistep_reasoning_and_approval_resume_loop(
    async_client: AsyncClient,
    setup_test_workspace: Path,
):
    """
    Test multi-step execution loop:
    Cycle 1: read file A -> observe
    Cycle 2: read file B -> observe
    Cycle 3: write file C (requires approval) -> interrupt!
    Cycle 4: approve decision -> resume -> execute write -> observe
    Cycle 5: direct final response -> completed!
    """
    # 1. Setup workspace files
    file_a = setup_test_workspace / "config_a.txt"
    file_a.write_text("HOST=localhost", encoding="utf-8")
    file_b = setup_test_workspace / "config_b.txt"
    file_b.write_text("PORT=8080", encoding="utf-8")

    session_id = "sess-multistep-1"

    # Configure mock responses for sequential reasoning turns
    mock = model_router.get_provider("mock")
    assert isinstance(mock, MockModelProvider)
    mock.clear_queue()

    # Turn 1: request read file A
    mock.queue_response(
        ModelResponse(
            content="Reading config_a...",
            tool_calls=[ToolCallRequest(id="call_1", name="read_workspace_file", arguments={"path": "config_a.txt"})],
            finish_reason="tool_calls",
        )
    )
    # Turn 2: observe file A, request read file B
    mock.queue_response(
        ModelResponse(
            content="Observed config_a. Reading config_b...",
            tool_calls=[ToolCallRequest(id="call_2", name="read_workspace_file", arguments={"path": "config_b.txt"})],
            finish_reason="tool_calls",
        )
    )
    # Turn 3: observe file B, request write combined config C (requires approval)
    mock.queue_response(
        ModelResponse(
            content="Observed config_b. Writing combined config...",
            tool_calls=[ToolCallRequest(id="call_3", name="write_workspace_file", arguments={"path": "config_c.txt", "content": "HOST=localhost:8080"})],
            finish_reason="tool_calls",
        )
    )
    # Turn 4: after approval resume and observing write, return final response
    mock.queue_response(
        ModelResponse(
            content="Successfully inspected configs and generated combined configuration in config_c.txt.",
            tool_calls=[],
            finish_reason="stop",
        )
    )

    # 2. Start execution
    resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Inspect configs and create combined config_c.txt"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Step 3 write_workspace_file triggered interrupt
    assert data["status"] == "waiting_for_approval"
    approval_id = data["approval_id"]
    assert approval_id is not None
    run_id = data["run_id"]

    # Verify file C not created yet
    file_c = setup_test_workspace / "config_c.txt"
    assert not file_c.exists()

    # 3. Approve write_workspace_file
    dec_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Approved combined config write"},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()

    assert dec_data["status"] == "approved"
    assert dec_data["execution_status"] == "completed"
    assert "Successfully inspected configs and generated combined configuration" in dec_data["final_response"]

    # Verify file C was written
    assert file_c.exists()
    assert file_c.read_text(encoding="utf-8") == "HOST=localhost:8080"

    # 4. Verify step numbers in audit traces
    run_resp = await async_client.get(f"/v1/runs/{run_id}")
    assert run_resp.status_code == 200
    run_events = run_resp.json()["events"]
    step_events = [e for e in run_events if e["event_type"] == "step_completed"]
    assert len(step_events) >= 2
    steps = [e["payload"]["step"] for e in step_events]
    assert steps == sorted(steps)


@pytest.mark.asyncio
async def test_bounded_control_max_steps(async_client: AsyncClient, setup_test_workspace: Path):
    """Verify execution halts cleanly when max_steps budget is exhausted."""
    f = setup_test_workspace / "loop.txt"
    f.write_text("data", encoding="utf-8")

    mock = model_router.get_provider("mock")
    assert isinstance(mock, MockModelProvider)
    mock.clear_queue()

    # Queue 5 read requests when max_steps is set to 2
    for i in range(5):
        mock.queue_response(
            ModelResponse(
                content=f"Reading loop {i}...",
                tool_calls=[ToolCallRequest(id=f"call_loop_{i}", name="read_workspace_file", arguments={"path": "loop.txt"})],
                finish_reason="tool_calls",
            )
        )

    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": "sess-max-steps",
            "message": "Start loop",
            "metadata": {"max_steps": 2},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert "Maximum agent steps limit reached" in data["response"]


@pytest.mark.asyncio
async def test_bounded_control_max_consecutive_failures(async_client: AsyncClient):
    """Verify execution halts when too many consecutive tool failures occur."""
    mock = model_router.get_provider("mock")
    assert isinstance(mock, MockModelProvider)
    mock.clear_queue()

    # Queue reads for non-existent files to trigger consecutive failures
    for i in range(4):
        mock.queue_response(
            ModelResponse(
                content="Reading non-existent...",
                tool_calls=[ToolCallRequest(id=f"fail_{i}", name="read_workspace_file", arguments={"path": f"non_existent_{i}.txt"})],
                finish_reason="tool_calls",
            )
        )

    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": "sess-consec-fail",
            "message": "Trigger failures",
            "metadata": {"max_consecutive_failures": 2},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "Exceeded maximum consecutive tool failures" in data["response"]


@pytest.mark.asyncio
async def test_bounded_control_wall_clock_deadline(async_client: AsyncClient, setup_test_workspace: Path):
    """Verify execution halts when wall-clock deadline budget is exceeded."""
    f = setup_test_workspace / "dummy.txt"
    f.write_text("ok", encoding="utf-8")

    mock = model_router.get_provider("mock")
    assert isinstance(mock, MockModelProvider)
    mock.clear_queue()

    for i in range(5):
        mock.queue_response(
            ModelResponse(
                content="Reading dummy...",
                tool_calls=[ToolCallRequest(id=f"dummy_{i}", name="read_workspace_file", arguments={"path": "dummy.txt"})],
                finish_reason="tool_calls",
            )
        )

    # Set timeout budget to 0.001s (already expired by the time observe_node runs)
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": "sess-timeout",
            "message": "Trigger deadline",
            "metadata": {"timeout_seconds": 0.0001},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert "Wall-clock deadline exceeded" in data["response"]
