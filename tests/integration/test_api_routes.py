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
        json={"session_id": session_id, "project_name": "AURA Project", "message": "Hello AURA, who are you?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["approval_id"] is None
    assert data["user_message_id"]
    assert data["assistant_message_id"]
    assert "AURA Response" in data["response"]

    graph_resp = await async_client.get("/v1/workspace/projects/AURA%20Project/graph")
    assert graph_resp.status_code == 200
    graph = graph_resp.json()
    assert {item["source_message_id"] for item in graph["objects"]} == {data["user_message_id"], data["assistant_message_id"]}
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["relation_type"] == "reply"


@pytest.mark.asyncio
async def test_session_hydration_returns_sanitized_context_manifest(async_client: AsyncClient):
    object_response = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Migration constraint",
        "content": "Keep the migration reversible.",
    })
    assert object_response.status_code == 201

    chat_response = await async_client.post("/v1/chat", json={
        "session_id": "session-context-hydration",
        "project_name": "aura",
        "message": "Plan the migration.",
        "context_object_ids": [object_response.json()["id"]],
    })
    assert chat_response.status_code == 200

    session_response = await async_client.get("/v1/sessions/session-context-hydration")
    assert session_response.status_code == 200
    assistant = next(message for message in session_response.json()["messages"] if message["role"] == "assistant")
    assert assistant["run_id"] == chat_response.json()["run_id"]
    manifest = assistant["context_manifest"]
    assert manifest["objects"] == [{
        "object_id": object_response.json()["id"],
        "object_type": "manual_note",
        "selected_by_user": True,
        "source_object_ids": [],
    }]
    assert isinstance(manifest["estimated_tokens"], int)
    assert "prompt_text" not in manifest
    routing = assistant["routing_provenance"]
    assert routing["provider"] == "mock"
    assert routing["model"] == "mock-default"
    assert routing["role"] == "root"
    assert isinstance(routing["reasoning_effort"], str)


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
