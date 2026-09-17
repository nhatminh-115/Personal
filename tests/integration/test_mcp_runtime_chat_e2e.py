"""End-to-end integration tests wiring MCP tools directly into the AURA /v1/chat runtime."""

import sys
import pytest
from httpx import AsyncClient

from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import mcp_manager
from app.tools.registry import tool_registry


@pytest.fixture(autouse=True)
async def setup_mcp_server():
    """Register and discover tools from sample MCP server before tests."""
    config = MCPServerConfig(
        id="sample-mcp",
        name="Sample MCP Server",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        auto_approve_tools=["read_metric", "system_echo"],
        timeout_seconds=10.0,
    )
    mcp_manager.register_server(config)
    await mcp_manager.discover_tools("sample-mcp")

    yield

    await mcp_manager.disconnect_all()


@pytest.mark.asyncio
async def test_mcp_read_tool_auto_execution_in_chat(async_client: AsyncClient):
    """
    Verify that an MCP read-only tool is invoked by the LLM and auto-executed without interruption:
    /v1/chat -> LLM requests read_metric -> executed -> returns response.
    """
    session_id = "sess-mcp-read"
    resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Read metric cpu_utilization"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["approval_id"] is None
    assert "cpu_utilization" in data["response"]
    assert "99.9%" in data["response"]


@pytest.mark.asyncio
async def test_mcp_mutate_tool_approval_pause_and_resume(async_client: AsyncClient):
    """
    Verify that an MCP mutating/high-risk tool pauses for human approval via LangGraph interrupt
    and resumes cleanly upon authorization:
    1. /v1/chat -> LLM requests mutate_record -> paused with approval_id.
    2. Inspect approval record.
    3. /v1/approvals/{id}/decision -> approve -> graph resumes -> completed.
    """
    session_id = "sess-mcp-mutate"

    # 1. Trigger mutation tool call
    chat_resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Mutate record acc_999 to enterprise_plan"},
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert chat_data["status"] == "waiting_for_approval"
    approval_id = chat_data["approval_id"]
    assert approval_id is not None
    assert "requires human approval" in chat_data["response"]

    # 2. Check approval details
    appr_resp = await async_client.get(f"/v1/approvals/{approval_id}")
    assert appr_resp.status_code == 200
    appr_data = appr_resp.json()
    assert appr_data["tool_name"] == "mcp_sample-mcp_mutate_record"
    assert appr_data["risk_level"].lower() == "high"
    assert appr_data["status"] == "pending"

    # 3. Approve and resume
    dec_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorized by administrator"},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["status"] == "approved"
    assert dec_data["execution_status"] == "completed"
    assert "Record acc_999 updated to enterprise_plan" in dec_data["final_response"]
