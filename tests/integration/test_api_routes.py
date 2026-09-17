"""Integration tests for API routes: direct chat, approvals rejection, health, and error paths."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "AURA" in data["app"]


@pytest.mark.asyncio
async def test_direct_chat_turn(async_client: AsyncClient):
    session_id = "test-direct-sess"
    resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Hello AURA, who are you?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["approval_id"] is None
    assert "AURA Response" in data["response"]


@pytest.mark.asyncio
async def test_approval_rejection_flow(async_client: AsyncClient):
    session_id = "test-reject-sess"

    # 1. Trigger approval requirement
    chat_resp = await async_client.post(
        "/v1/chat",
        json={"session_id": session_id, "message": "Write confidential to confidential.txt"},
    )
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert chat_data["status"] == "waiting_for_approval"
    approval_id = chat_data["approval_id"]

    # 2. Reject the action
    decision_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "rejected", "decision_notes": "Security risk."},
    )
    assert decision_resp.status_code == 200
    data = decision_resp.json()
    assert data["status"] == "rejected"
    assert "rejected by the user" in data["final_response"]

    # 3. Trying to decide again on the same approval should fail (400)
    repeat_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved"},
    )
    assert repeat_resp.status_code == 400


@pytest.mark.asyncio
async def test_non_existent_approval_returns_404(async_client: AsyncClient):
    resp = await async_client.get("/v1/approvals/non-existent-id")
    assert resp.status_code == 404

    dec_resp = await async_client.post(
        "/v1/approvals/non-existent-id/decision",
        json={"decision": "approved"},
    )
    assert dec_resp.status_code == 404


@pytest.mark.asyncio
async def test_non_existent_run_returns_404(async_client: AsyncClient):
    resp = await async_client.get("/v1/runs/non-existent-run-id")
    assert resp.status_code == 404
