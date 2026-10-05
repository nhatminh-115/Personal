"""Integration tests for API routes: direct chat, approvals rejection, health, and error paths."""

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from httpx import AsyncClient
from app.db.models import (
    ApprovalModel, MemoryModel, MessageModel, RunEventModel, RunModel, SessionModel,
    WorkspaceObjectModel, WorkspaceObjectProjectLinkModel,
)
from app.orchestrator.graph import get_compiled_graph
from sqlalchemy import select


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    resp = await async_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "AURA" in data["app"]


@pytest.mark.asyncio
async def test_readiness_reports_database_and_durable_checkpointer(async_client: AsyncClient):
    resp = await async_client.get("/ready")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ready",
        "checks": {"database": "healthy", "checkpointer": "healthy"},
    }


@pytest.mark.asyncio
async def test_readiness_fails_when_checkpointer_is_not_initialized(async_client: AsyncClient, monkeypatch):
    async def unavailable_checkpointer():
        return False

    monkeypatch.setattr("app.api.server.is_checkpointer_available", unavailable_checkpointer)
    resp = await async_client.get("/ready")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "not_ready",
        "checks": {"database": "healthy", "checkpointer": "unavailable"},
    }


@pytest.mark.asyncio
async def test_readiness_detects_checkpointer_storage_failure(async_client: AsyncClient, monkeypatch):
    class BrokenCheckpointer:
        async def aget_tuple(self, _config):
            raise RuntimeError("private checkpoint storage failure")

    monkeypatch.setattr("app.orchestrator.graph._global_checkpointer", BrokenCheckpointer())
    resp = await async_client.get("/ready")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "not_ready",
        "checks": {"database": "healthy", "checkpointer": "unavailable"},
    }
    assert "private checkpoint" not in resp.text


@pytest.mark.asyncio
async def test_readiness_fails_when_database_is_unavailable(async_client: AsyncClient, test_db_session, monkeypatch):
    async def unavailable_database(*_args, **_kwargs):
        raise RuntimeError("database connection details must not be exposed")

    monkeypatch.setattr(test_db_session, "execute", unavailable_database)
    resp = await async_client.get("/ready")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable", "checkpointer": "healthy"},
    }
    assert "connection details" not in resp.text


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
async def test_chat_provider_failure_is_classified_and_redacted(
    async_client: AsyncClient,
    test_db_session,
    monkeypatch,
):
    from app.core.errors import ProviderError

    class FailingGraph:
        async def ainvoke(self, *_args, **_kwargs):
            raise ProviderError(
                "Provider ollama returned status 500: private runner diagnostic",
                details={"body": "private runner diagnostic"},
            )

    async def get_failing_graph():
        return FailingGraph()

    monkeypatch.setattr("app.api.routes.chat.get_compiled_graph", get_failing_graph)
    response = await async_client.post("/v1/chat", json={
        "session_id": "provider-failure-session",
        "project_name": "Provider Failure Project",
        "message": "Test provider failure handling.",
    })

    assert response.status_code == 502
    assert response.json() == {
        "error": "ModelProviderError",
        "code": "ModelProviderError",
        "message": "The selected model provider could not complete this request. Check provider availability and routing settings, then retry.",
        "details": {},
    }
    assert "private runner diagnostic" not in response.text

    run = await test_db_session.scalar(
        select(RunModel)
        .where(RunModel.session_id == "provider-failure-session")
        .order_by(RunModel.created_at.desc(), RunModel.id.desc())
    )
    assert run is not None
    assert run.status == "failed"
    assert run.error_message == "Model provider request failed."
    assert "private runner diagnostic" not in run.error_message

    events = await test_db_session.scalars(
        select(RunEventModel).where(
            RunEventModel.run_id == run.id,
            RunEventModel.event_type == "run_failed",
        )
    )
    failed_event = events.one()
    assert failed_event.payload == {"error_category": "provider_failure"}


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
async def test_explicit_local_file_text_requires_cloud_confirmation_and_stays_out_of_trace(
    async_client: AsyncClient,
    test_db_session,
):
    object_id = str(uuid.uuid4())
    private_file_text = "private selected file text marker"
    test_db_session.add_all([
        WorkspaceObjectModel(
            id=object_id,
            project_name=None,
            object_type="file_reference",
            created_by="user",
            title="Research notes.md",
            content="",
            metadata_json={"storage_location": "browser_local"},
        ),
        WorkspaceObjectProjectLinkModel(object_id=object_id, project_name="File Context Project"),
    ])
    await test_db_session.commit()

    response = await async_client.post("/v1/chat", json={
        "session_id": "file-context-session",
        "project_name": "File Context Project",
        "message": "Summarize the selected file.",
        "context_object_ids": [object_id],
        "context_attachments": [{"object_id": object_id, "text": private_file_text}],
    })
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    run = await test_db_session.get(RunModel, run_id)
    assert run is not None
    assert run.routing_snapshot_json["require_cloud_confirmation"] is True
    assert run.routing_snapshot_json["fallback_policy"] == "cloud_allowed"

    graph = await get_compiled_graph()
    snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
    assert private_file_text in "\n".join(snapshot.values["retrieved_context"])

    event_result = await test_db_session.execute(select(RunEventModel).where(RunEventModel.run_id == run_id))
    events = list(event_result.scalars())
    assert any(event.event_type == "context_compiled" for event in events)
    assert all(private_file_text not in str(event.payload) for event in events)


@pytest.mark.asyncio
async def test_file_text_attachment_requires_visible_project_reference(async_client: AsyncClient):
    response = await async_client.post("/v1/chat", json={
        "session_id": "file-context-scope-session",
        "project_name": "File Context Project",
        "message": "Use this file.",
        "context_object_ids": ["not-a-visible-file-reference"],
        "context_attachments": [{"object_id": "not-a-visible-file-reference", "text": "private"}],
    })

    assert response.status_code == 422
    assert "visible Library reference" in response.text


@pytest.mark.asyncio
async def test_session_history_uses_cursor_pages_without_overlap(async_client: AsyncClient, test_db_session):
    session_id = "session-history-pagination"
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    test_db_session.add(SessionModel(id=session_id, title="History pagination", project_name="Atlas"))
    test_db_session.add_all([
        MessageModel(
            id=f"history-{index:03d}",
            session_id=session_id,
            role="user" if index % 2 == 0 else "assistant",
            content=f"Message {index}",
            created_at=base_time + timedelta(seconds=index),
        )
        for index in range(105)
    ])
    await test_db_session.commit()

    first_response = await async_client.get(f"/v1/sessions/{session_id}")
    assert first_response.status_code == 200
    first_page = first_response.json()
    assert [message["content"] for message in first_page["messages"]] == [f"Message {i}" for i in range(5, 105)]
    assert first_page["project_name"] == "Atlas"
    assert first_page["messages_next_cursor"]

    second_response = await async_client.get(
        f"/v1/sessions/{session_id}", params={"cursor": first_page["messages_next_cursor"]},
    )
    assert second_response.status_code == 200
    second_page = second_response.json()
    assert [message["content"] for message in second_page["messages"]] == [f"Message {i}" for i in range(5)]
    assert second_page["messages_next_cursor"] is None
    assert {message["id"] for message in first_page["messages"]}.isdisjoint(
        message["id"] for message in second_page["messages"]
    )


@pytest.mark.asyncio
async def test_session_execution_state_restores_latest_root_and_pending_child_approval(async_client: AsyncClient, test_db_session):
    session_id = "session-execution-state"
    old_run_id = "old-session-run"
    root_run_id = "latest-session-run"
    child_run_id = "latest-session-child"
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    test_db_session.add(SessionModel(id=session_id, title="Execution recovery"))
    test_db_session.add_all([
        RunModel(
            id=old_run_id, session_id=session_id, user_message="older turn", status="completed",
            created_at=base_time, updated_at=base_time,
        ),
        RunModel(
            id=root_run_id, session_id=session_id, user_message="latest turn", status="waiting_for_approval",
            created_at=base_time + timedelta(seconds=1), updated_at=base_time + timedelta(seconds=2),
        ),
        RunModel(
            id=child_run_id, session_id=session_id, parent_run_id=root_run_id,
            user_message="specialist turn", status="waiting_for_approval",
            created_at=base_time + timedelta(seconds=2), updated_at=base_time + timedelta(seconds=2),
        ),
        ApprovalModel(
            id="stale-approval", run_id=old_run_id, session_id=session_id,
            tool_name="old_tool", tool_input={"command": "old"}, status="pending",
            created_at=base_time + timedelta(seconds=3),
        ),
        ApprovalModel(
            id="child-pending-approval", run_id=child_run_id, session_id=session_id,
            tool_name="shell", tool_input={"command": "inspect"}, status="pending",
            created_at=base_time + timedelta(seconds=4),
        ),
    ])
    await test_db_session.commit()

    response = await async_client.get(f"/v1/sessions/{session_id}/state")

    assert response.status_code == 200
    state = response.json()
    assert state["session_id"] == session_id
    assert state["run_id"] == root_run_id
    assert state["run_status"] == "waiting_for_approval"
    assert state["approval"] == {
        "id": "child-pending-approval",
        "run_id": child_run_id,
        "session_id": session_id,
        "tool_call_id": None,
        "tool_name": "shell",
        "tool_input": {"command": "inspect"},
        "risk_level": "HIGH",
        "status": "pending",
        "decision_notes": None,
        "created_at": state["approval"]["created_at"],
        "decided_at": None,
    }
    assert state["approval"]["created_at"].startswith("2026-01-01T00:00:04")


@pytest.mark.asyncio
async def test_session_execution_state_omits_approval_after_run_is_resolved(async_client: AsyncClient, test_db_session):
    session_id = "session-execution-resolved"
    run_id = "resolved-session-run"
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    test_db_session.add(SessionModel(id=session_id))
    test_db_session.add(RunModel(
        id=run_id, session_id=session_id, user_message="resolved turn", status="completed",
        created_at=base_time, updated_at=base_time,
    ))
    test_db_session.add(ApprovalModel(
        id="resolved-approval", run_id=run_id, session_id=session_id,
        tool_name="shell", tool_input={"command": "done"}, status="approved",
        created_at=base_time, decided_at=base_time,
    ))
    await test_db_session.commit()

    response = await async_client.get(f"/v1/sessions/{session_id}/state")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "run_id": run_id,
        "run_status": "completed",
        "client_turn_id": None,
        "approval": None,
    }


@pytest.mark.asyncio
async def test_memory_inspector_uses_cursor_pages_without_overlap(async_client: AsyncClient, test_db_session):
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    test_db_session.add_all([
        MemoryModel(
            id=str(index + 1).zfill(36),
            memory_type="semantic",
            project_name="Memory Pagination Project",
            key=f"memory-{index:02d}",
            content=f"Memory content {index}",
            created_at=base_time + timedelta(seconds=index),
        )
        for index in range(31)
    ])
    await test_db_session.commit()

    first_response = await async_client.get("/v1/memory", params={"project_name": "Memory Pagination Project"})
    assert first_response.status_code == 200
    first_page = first_response.json()
    assert [item["key"] for item in first_page] == [f"memory-{index:02d}" for index in range(30, 5, -1)]
    cursor = first_response.headers.get("X-Next-Cursor")
    assert cursor

    second_response = await async_client.get(
        "/v1/memory",
        params={"project_name": "Memory Pagination Project", "cursor": cursor},
    )
    assert second_response.status_code == 200
    second_page = second_response.json()
    assert [item["key"] for item in second_page] == [f"memory-{index:02d}" for index in range(5, -1, -1)]
    assert {item["id"] for item in first_page}.isdisjoint(item["id"] for item in second_page)
    assert second_response.headers.get("X-Next-Cursor") is None


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
async def test_chat_turn_cancellation_is_durable_and_idempotent(async_client: AsyncClient, test_db_session):
    session_id, turn_id, run_id = "cancel-turn-session", "cancel-turn-key", "cancel-turn-run"
    test_db_session.add_all([
        SessionModel(id=session_id),
        RunModel(
            id=run_id,
            session_id=session_id,
            client_turn_id=turn_id,
            status="running",
            user_message="A long running task",
        ),
    ])
    await test_db_session.commit()

    payload = {"session_id": session_id, "client_turn_id": turn_id}
    response = await async_client.post("/v1/runs/cancel-turn", json=payload)
    assert response.status_code == 202, response.text
    assert response.json() == {
        "run_id": run_id,
        "status": "cancellation_requested",
        "already_requested": False,
    }

    run = await test_db_session.get(RunModel, run_id)
    await test_db_session.refresh(run)
    assert run.cancel_requested_at is not None
    events = list((await test_db_session.scalars(
        select(RunEventModel).where(RunEventModel.run_id == run_id)
    )).all())
    assert [event.event_type for event in events] == ["run_cancellation_requested"]

    repeated = await async_client.post("/v1/runs/cancel-turn", json=payload)
    assert repeated.status_code == 202
    assert repeated.json()["already_requested"] is True

    run.status = "completed"
    await test_db_session.commit()
    completed = await async_client.post("/v1/runs/cancel-turn", json=payload)
    assert completed.status_code == 409


@pytest.mark.asyncio
async def test_chat_turn_cancellation_rejects_unknown_turn(async_client: AsyncClient):
    response = await async_client.post(
        "/v1/runs/cancel-turn",
        json={"session_id": "missing-session", "client_turn_id": "missing-turn"},
    )
    assert response.status_code == 404


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
