"""E2E Security Test: Workspace jail escape prevention.

Attempt:
../../outside.txt
Expected:
ACCESS DENIED
"""

from pathlib import Path
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_e2e_workspace_escape_blocked(async_client: AsyncClient, setup_test_workspace: Path):
    session_id = "e2e-security-sess-1"

    # User attempts to read outside the workspace sandbox
    chat_resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Read ../../outside.txt"},
    )
    assert chat_resp.status_code == 200
    data = chat_resp.json()

    # The tool execution must fail safely with an error mentioning ACCESS DENIED
    assert len(data["tool_results"]) == 1
    tool_result = data["tool_results"][0]["result"]
    assert tool_result["success"] is False
    assert "ACCESS DENIED" in tool_result["error"]
