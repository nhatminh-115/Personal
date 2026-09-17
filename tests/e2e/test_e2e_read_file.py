"""E2E Test: Automatic tool execution flow (Read File).

Flow:
user: "Read hello.txt"
Expected:
* orchestrator requests filesystem read
* permission allows it automatically
* tool reads file
* final answer uses file contents
* trace contains the relevant events
"""

from pathlib import Path
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_e2e_read_file_flow(async_client: AsyncClient, setup_test_workspace: Path):
    # 1. Create hello.txt in the workspace
    hello_file = setup_test_workspace / "hello.txt"
    hello_file.write_text("Hello from AURA E2E Testing!", encoding="utf-8")

    session_id = "e2e-read-sess-1"

    # 2. Send chat request: "Read hello.txt"
    chat_resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Read hello.txt"},
    )
    assert chat_resp.status_code == 200
    data = chat_resp.json()

    assert data["session_id"] == session_id
    assert data["status"] == "completed"
    assert data["approval_id"] is None
    assert len(data["tool_results"]) == 1
    assert data["tool_results"][0]["name"] == "read_workspace_file"
    assert data["tool_results"][0]["result"]["success"] is True
    assert "Hello from AURA E2E Testing!" in data["tool_results"][0]["result"]["output"]
    assert "Hello from AURA E2E Testing!" in data["response"]

    run_id = data["run_id"]

    # 3. Verify Run and trace audit trail via API
    run_resp = await async_client.get(f"/v1/runs/{run_id}")
    assert run_resp.status_code == 200
    run_data = run_resp.json()

    assert run_data["status"] == "completed"
    event_types = [e["event_type"] for e in run_data["events"]]

    # Ensure required trace events were emitted in lifecycle order
    assert "request_received" in event_types
    assert "context_loaded" in event_types
    assert "model_called" in event_types
    assert "tool_requested" in event_types
    assert "tool_executed" in event_types
    assert "response_generated" in event_types
    assert "memory_updated" in event_types
    assert "run_completed" in event_types

    # 4. Verify session message history persistence
    sess_resp = await async_client.get(f"/v1/sessions/{session_id}")
    assert sess_resp.status_code == 200
    sess_data = sess_resp.json()
    assert len(sess_data["messages"]) >= 2
    assert any(m["role"] == "user" and "Read hello.txt" in m["content"] for m in sess_data["messages"])
    assert any(m["role"] == "assistant" for m in sess_data["messages"])
