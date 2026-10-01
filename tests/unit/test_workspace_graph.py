"""Durable shared workspace graph API invariants."""

from datetime import datetime, timedelta, timezone

import pytest

from app.memory.service import SQLMemoryService
from app.db.models import MessageModel, RunEventModel, RunModel, SessionModel, WorkspaceObjectModel


@pytest.mark.asyncio
async def test_context_flow_is_a_dag_while_semantic_relations_can_cycle(async_client):
    async def note(title: str) -> str:
        response = await async_client.post(
            "/v1/workspace/projects/aura/objects",
            json={"object_type": "manual_note", "title": title, "content": f"Body: {title}"},
        )
        assert response.status_code == 201
        return response.json()["id"]

    first, second, third = await note("A"), await note("B"), await note("C")

    async def edge(source: str, target: str, family: str):
        return await async_client.post(
            "/v1/workspace/projects/aura/edges",
            json={
                "source_object_id": source,
                "target_object_id": target,
                "relation_type": "related_to" if family == "semantic" else "feeds",
                "edge_family": family,
            },
        )

    assert (await edge(first, second, "context")).status_code == 201
    assert (await edge(second, third, "context")).status_code == 201
    assert (await edge(third, first, "context")).status_code == 409
    assert (await edge(first, third, "semantic")).status_code == 201
    assert (await edge(third, first, "semantic")).status_code == 201

    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert len(graph["objects"]) == 3
    assert len(graph["edges"]) == 4


@pytest.mark.asyncio
async def test_context_bridge_and_manual_note_are_user_authored_and_editable(async_client):
    source = await async_client.post(
        "/v1/workspace/projects/aura/objects",
        json={"object_type": "manual_note", "title": "Source", "content": "Keep exact wording."},
    )
    assert source.status_code == 201

    bridge = await async_client.post(
        "/v1/workspace/projects/aura/objects",
        json={
            "object_type": "context_bridge",
            "title": "Handoff",
            "content": "Selected conclusions only.",
            "source_object_ids": [source.json()["id"]],
            "metadata_json": {"include_failed_attempts": False},
        },
    )
    assert bridge.status_code == 201
    assert bridge.json()["created_by"] == "user"

    updated = await async_client.put(
        f"/v1/workspace/projects/aura/objects/{source.json()['id']}",
        json={"title": "Source edited", "content": "Keep exact wording, edited by the user.", "metadata_json": {}},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "Keep exact wording, edited by the user."
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert any(edge["relation_type"] == "bridges_to" for edge in graph["edges"])

    branch = await async_client.post(
        "/v1/workspace/projects/aura/objects",
        json={
            "object_type": "conversation_branch",
            "title": "Branch from source",
            "content": "",
            "source_object_ids": [source.json()["id"]],
        },
    )
    assert branch.status_code == 201
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert any(edge["relation_type"] == "branches_to" and edge["target_object_id"] == branch.json()["id"] for edge in graph["edges"])


@pytest.mark.asyncio
async def test_workspace_graph_is_project_scoped_and_layout_uses_optimistic_revision(async_client):
    note = await async_client.post(
        "/v1/workspace/projects/aura/objects",
        json={"object_type": "manual_note", "title": "AURA only", "content": "project"},
    )
    note_id = note.json()["id"]
    foreign_edge = await async_client.post(
        "/v1/workspace/projects/transportability/edges",
        json={"source_object_id": note_id, "target_object_id": note_id, "relation_type": "same", "edge_family": "semantic"},
    )
    assert foreign_edge.status_code == 422
    assert (await async_client.get("/v1/workspace/projects/transportability/graph")).json()["objects"] == []

    saved = await async_client.put(
        "/v1/workspace/projects/aura/layout",
        json={"layout": {"nodes": {note_id: {"x": 12, "y": 34}}, "viewport": {"zoom": 0.8}}, "expected_revision": 0},
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["layout"]["nodes"][note_id] == {"x": 12, "y": 34}

    stale = await async_client.put(
        "/v1/workspace/projects/aura/layout",
        json={"layout": {"nodes": {}}, "expected_revision": 0},
    )
    assert stale.status_code == 409
    assert (await async_client.get("/v1/workspace/projects/aura/graph")).json()["layout"]["revision"] == 1


@pytest.mark.asyncio
async def test_live_conversation_messages_are_project_graph_objects(test_db_session):
    service = SQLMemoryService(test_db_session)
    session = await service.get_or_create_session("workspace-project-session")
    session.project_name = "aura"
    await test_db_session.commit()

    user = await service.save_message(session.id, "user", "Ask a question", metadata={"run_id": "run-1"})
    assistant = await service.save_message(session.id, "assistant", "Answer carefully", metadata={"run_id": "run-1"})

    from sqlalchemy import select
    from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel

    objects = list((await test_db_session.execute(select(WorkspaceObjectModel).where(WorkspaceObjectModel.project_name == "aura"))).scalars())
    edges = list((await test_db_session.execute(select(WorkspaceEdgeModel).where(WorkspaceEdgeModel.project_name == "aura"))).scalars())
    assert {item.source_message_id for item in objects} == {user.id, assistant.id}
    assert len(edges) == 1
    assert (edges[0].source_object_id, edges[0].target_object_id, edges[0].relation_type) == (
        next(item.id for item in objects if item.source_message_id == user.id),
        next(item.id for item in objects if item.source_message_id == assistant.id),
        "reply",
    )


@pytest.mark.asyncio
async def test_session_cannot_be_reassigned_to_another_project(async_client, test_db_session):
    service = SQLMemoryService(test_db_session)
    session = await service.get_or_create_session("project-bound-session")
    session.project_name = "AURA Project"
    await test_db_session.commit()

    response = await async_client.post("/v1/chat", json={
        "session_id": session.id,
        "project_name": "Other Project",
        "message": "This must not cross project boundaries.",
    })
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_chat_compiles_selected_workspace_context_and_records_provenance(async_client, test_db_session):
    from app.db.models import WorkspaceObjectModel
    from app.models.router import model_router
    from app.models.base import ModelRole

    selected = WorkspaceObjectModel(
        id="selected-context-note", project_name="aura", object_type="manual_note",
        created_by="user", title="Constraint", content="Keep the schema migration reversible.",
    )
    other_project = WorkspaceObjectModel(
        id="unselected-other-project", project_name="elsewhere", object_type="manual_note",
        created_by="user", title="Secret", content="This belongs to another project.",
    )
    test_db_session.add_all([selected, other_project])
    await test_db_session.commit()

    response = await async_client.post("/v1/chat", json={
        "session_id": "compiled-context-session",
        "project_name": "aura",
        "message": "Plan this migration.",
        "context_object_ids": [selected.id],
    })

    assert response.status_code == 200
    request = model_router.get_provider("mock").call_history[-1]
    system_message = next(message for message in request.messages if message.role == ModelRole.SYSTEM)
    assert selected.id in system_message.content
    assert "Keep the schema migration reversible." in system_message.content
    assert "This belongs to another project." not in system_message.content

    run = (await async_client.get(f"/v1/runs/{response.json()['run_id']}")).json()
    compiled_event = next(event for event in run["events"] if event["event_type"] == "context_compiled")
    assert compiled_event["payload"]["objects"] == [{
        "object_id": selected.id,
        "object_type": "manual_note",
        "selected_by_user": True,
        "source_object_ids": [],
    }]
    assert compiled_event["payload"]["estimated_tokens"] > 0

    calls_before_invalid = len(model_router.get_provider("mock").call_history)
    invalid = await async_client.post("/v1/chat", json={
        "session_id": "compiled-context-cross-project",
        "project_name": "aura",
        "message": "This must not run.",
        "context_object_ids": [other_project.id],
    })
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "ContextSelectionError"
    assert len(model_router.get_provider("mock").call_history) == calls_before_invalid


@pytest.mark.asyncio
async def test_chat_compiles_only_selected_bridge_sections_and_records_section_provenance(async_client):
    from app.models.router import model_router
    from app.models.base import ModelRole

    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note", "title": "Source constraint", "content": "Full source text must stay out of Bridge context.",
        "metadata_json": {"privacy_policy": "local_only"},
    })
    assert source.status_code == 201
    bridge = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "context_bridge",
        "title": "Selected migration handoff",
        "content": "Keep rollback available.",
        "metadata_json": {
            "bridge_options": {"conclusions": True, "observations": False, "failed": False, "artifacts": True},
            "bridge_sections": {
                "conclusions": "Deploy in reversible stages.",
                "observations": "Disabled observation must stay out.",
                "failed": "",
                "artifacts": "Migration checklist v2.",
            },
        },
        "source_object_ids": [source.json()["id"]],
    })
    assert bridge.status_code == 201

    response = await async_client.post("/v1/chat", json={
        "session_id": "bridge-compiled-context-session",
        "project_name": "aura",
        "message": "Continue the migration plan.",
        "context_object_ids": [bridge.json()["id"]],
    })

    assert response.status_code == 200
    request = model_router.get_provider("mock").call_history[-1]
    system_message = next(message for message in request.messages if message.role == ModelRole.SYSTEM)
    assert "Keep rollback available." in system_message.content
    assert "Deploy in reversible stages." in system_message.content
    assert "Migration checklist v2." in system_message.content
    assert "Disabled observation must stay out." not in system_message.content
    assert "Full source text must stay out of Bridge context." not in system_message.content

    run = (await async_client.get(f"/v1/runs/{response.json()['run_id']}")).json()
    compiled_event = next(event for event in run["events"] if event["event_type"] == "context_compiled")
    assert compiled_event["payload"]["privacy_requirement"] == "local_only"
    assert compiled_event["payload"]["objects"] == [{
        "object_id": bridge.json()["id"],
        "object_type": "context_bridge",
        "selected_by_user": True,
        "source_object_ids": [source.json()["id"]],
        "selected_sections": {
            "conclusions": True,
            "observations": False,
            "failed": False,
            "artifacts": True,
        },
    }]
    selected_model = next(event for event in run["events"] if event["event_type"] == "model_selected")
    assert selected_model["payload"]["privacy"] == "local_only"

    calls_before_cloud_lock = len(model_router.get_provider("mock").call_history)
    cloud_locked = await async_client.post("/v1/chat", json={
        "session_id": "bridge-privacy-cloud-lock-session",
        "project_name": "aura",
        "message": "This must stay local.",
        "model_override": "openai:gpt-4o",
        "context_object_ids": [bridge.json()["id"]],
    })
    assert cloud_locked.status_code == 403
    assert cloud_locked.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before_cloud_lock


@pytest.mark.asyncio
async def test_attaching_existing_live_session_backfills_canonical_message_graph(async_client, test_db_session):
    session = SessionModel(id="legacy-live-session", title="Legacy", metadata_json={})
    test_db_session.add(session)
    await test_db_session.flush()
    created_at = datetime.now(timezone.utc)
    test_db_session.add_all([
        MessageModel(id="legacy-user-message", session_id=session.id, role="user", content="Old user turn", created_at=created_at),
        MessageModel(id="legacy-assistant-message", session_id=session.id, role="assistant", content="Old answer", created_at=created_at + timedelta(seconds=1)),
    ])
    await test_db_session.commit()

    attached = await async_client.post("/v1/workspace/projects/aura/sessions/legacy-live-session")
    assert attached.status_code == 200
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert {item["source_message_id"] for item in graph["objects"]} == {"legacy-user-message", "legacy-assistant-message"}
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["relation_type"] == "reply"
    assert (await async_client.post("/v1/workspace/projects/aura/sessions/missing-session")).status_code == 404


@pytest.mark.asyncio
async def test_workspace_graph_projects_sanitized_execution_trace_to_turns(async_client, test_db_session):
    session = SessionModel(id="trace-session", title="Trace", metadata_json={}, project_name="aura")
    run = RunModel(id="trace-run", session_id=session.id, status="completed", user_message="private user prompt")
    user = WorkspaceObjectModel(
        id="trace-user-object", project_name="aura", session_id=session.id, object_type="conversation_turn",
        created_by="user", title="Question", content="private user prompt", metadata_json={"role": "user", "run_id": run.id},
    )
    assistant = WorkspaceObjectModel(
        id="trace-answer-object", project_name="aura", session_id=session.id, object_type="conversation_turn",
        created_by="assistant", title="Answer", content="private assistant response", metadata_json={"role": "assistant", "run_id": run.id},
    )
    events = [
        RunEventModel(id="trace-model-event", run_id=run.id, event_type="model_selected", payload={
            "agent_role": "root", "provider": "local", "model": "test-model", "prompt": "private prompt secret",
        }),
        RunEventModel(id="trace-tool-request", run_id=run.id, event_type="tool_requested", payload={
            "tool": "workspace.read", "tool_call_id": "call-1", "arguments": {"path": "secret/path.txt"},
        }),
        RunEventModel(id="trace-tool-result", run_id=run.id, event_type="tool_executed", payload={
            "tool": "workspace.read", "result": {"success": True, "output": "private tool output secret"},
        }),
        RunEventModel(id="trace-unrelated-event", run_id=run.id, event_type="internal_reasoning", payload={"text": "never expose"}),
    ]
    test_db_session.add_all([session, run, user, assistant, *events])
    await test_db_session.commit()

    response = await async_client.get("/v1/workspace/projects/aura/graph")
    assert response.status_code == 200
    graph = response.json()
    [trace] = graph["execution_traces"]
    assert trace["run_id"] == run.id
    assert trace["user_object_id"] == user.id
    assert trace["response_object_id"] == assistant.id
    assert [event["event_type"] for event in trace["events"]] == ["model_selected", "tool_requested", "tool_executed"]
    tool_result = next(event for event in trace["events"] if event["event_type"] == "tool_executed")
    assert tool_result["tool_name"] == "workspace.read"
    assert tool_result["success"] is True
    serialized = response.text
    for private_value in ("private prompt secret", "secret/path.txt", "private tool output secret", "never expose"):
        assert private_value not in serialized
