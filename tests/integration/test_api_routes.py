"""Integration tests for API routes: direct chat, approvals rejection, health, and error paths."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from app.db.models import RunEventModel, RunModel, SessionModel


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
async def test_get_missing_session_returns_404_without_creating_it(async_client: AsyncClient, test_db_session):
    session_id = "read-only-session-lookup"

    response = await async_client.get(f"/v1/sessions/{session_id}")

    assert response.status_code == 404
    assert await test_db_session.get(SessionModel, session_id) is None


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


@pytest.mark.asyncio
async def test_run_inspector_exposes_operational_trace_without_private_payloads(
    async_client: AsyncClient,
    test_db_session,
):
    session_id, run_id = "inspector-safe-session", "inspector-safe-run"
    test_db_session.add_all([
        SessionModel(id=session_id),
        RunModel(id=run_id, session_id=session_id, status="completed", user_message="private original prompt"),
        RunEventModel(run_id=run_id, event_type="request_received", payload={"message": "private original prompt"}),
        RunEventModel(run_id=run_id, event_type="context_compiled", payload={
            "estimated_tokens": 128,
            "prompt_text": "private compiled prompt",
            "objects": [{"object_id": "note-1", "object_type": "manual_note", "selected_by_user": True, "content": "private note content"}],
        }),
        RunEventModel(run_id=run_id, event_type="tool_requested", payload={
            "tool": "workspace.read", "tool_call_id": "call-1", "arguments": {"path": "private/path.txt"},
        }),
        RunEventModel(run_id=run_id, event_type="tool_executed", payload={
            "tool": "workspace.read", "tool_call_id": "call-1",
            "result": {"success": True, "output": "private tool output", "metadata": {"secret": "private metadata"}},
        }),
        RunEventModel(run_id=run_id, event_type="internal_reasoning", payload={"text": "private hidden reasoning"}),
    ])
    await test_db_session.commit()

    response = await async_client.get(f"/v1/runs/{run_id}")
    assert response.status_code == 200
    run = response.json()
    compiled = next(event for event in run["events"] if event["event_type"] == "context_compiled")
    request = next(event for event in run["events"] if event["event_type"] == "request_received")
    tool_request = next(event for event in run["events"] if event["event_type"] == "tool_requested")
    tool_result = next(event for event in run["events"] if event["event_type"] == "tool_executed")
    assert compiled["payload"]["objects"][0]["object_id"] == "note-1"
    assert "message" not in request["payload"]
    assert tool_request["payload"]["tool"] == "workspace.read"
    assert tool_result["payload"]["result"] == {"success": True}
    for private_value in (
        "private compiled prompt", "private note content",
        "private/path.txt", "private tool output", "private metadata", "private hidden reasoning",
    ):
        assert private_value not in response.text
    for private_value in ("private original prompt", "private compiled prompt", "private note content"):
        assert private_value not in str(run["events"])


@pytest.mark.asyncio
async def test_run_inspector_paginates_trace_events_with_stable_keyset_cursor(
    async_client: AsyncClient,
    test_db_session,
):
    session_id, run_id = "inspector-page-session", "inspector-page-run"
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    test_db_session.add(SessionModel(id=session_id))
    test_db_session.add(RunModel(id=run_id, session_id=session_id, status="completed", user_message="hello"))
    test_db_session.add_all([
        RunEventModel(
            id=f"trace-event-{index:03d}",
            run_id=run_id,
            event_type="run_completed",
            payload={"status": str(index)},
            created_at=base_time + timedelta(seconds=index),
        )
        for index in range(5)
    ])
    await test_db_session.commit()

    first = await async_client.get(f"/v1/runs/{run_id}?page_size=2")
    assert first.status_code == 200, first.text
    assert [event["payload"]["status"] for event in first.json()["events"]] == ["0", "1"]
    cursor = first.headers.get("X-Next-Cursor")
    assert cursor

    second = await async_client.get(f"/v1/runs/{run_id}?page_size=2&cursor={cursor}")
    assert second.status_code == 200
    assert [event["payload"]["status"] for event in second.json()["events"]] == ["2", "3"]
    cursor = second.headers.get("X-Next-Cursor")
    assert cursor

    third = await async_client.get(f"/v1/runs/{run_id}?page_size=2&cursor={cursor}")
    assert third.status_code == 200
    assert [event["payload"]["status"] for event in third.json()["events"]] == ["4"]
    assert "X-Next-Cursor" not in third.headers


@pytest.mark.asyncio
async def test_run_inspector_rejects_invalid_event_cursor(async_client: AsyncClient, test_db_session):
    session_id, run_id = "inspector-invalid-cursor-session", "inspector-invalid-cursor-run"
    test_db_session.add_all([
        SessionModel(id=session_id),
        RunModel(id=run_id, session_id=session_id, status="completed", user_message="hello"),
    ])
    await test_db_session.commit()

    response = await async_client.get(f"/v1/runs/{run_id}?cursor=invalid")
    assert response.status_code == 422
