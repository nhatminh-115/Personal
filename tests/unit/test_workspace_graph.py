"""Durable shared workspace graph API invariants."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.service import SQLMemoryService
from app.db.models import MessageModel, RunEventModel, RunModel, SessionModel, WorkspaceObjectModel
from app.core.errors import ContextSelectionError
from app.memory.context_compiler import MAX_COMPILED_OBJECTS, WorkspaceContextCompiler


@pytest.mark.asyncio
async def test_context_compiler_rejects_excess_roots_before_database_reads():
    db = AsyncMock()

    with pytest.raises(ContextSelectionError) as error:
        await WorkspaceContextCompiler(db).compile(
            "aura", [f"selected-{index}" for index in range(MAX_COMPILED_OBJECTS + 1)]
        )

    assert error.value.details["object_limit"] == MAX_COMPILED_OBJECTS
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_context_compiler_rejects_excess_provenance_edges_before_loading_sources():
    db = AsyncMock()
    root = SimpleNamespace(id="context-root", object_type="manual_note")
    root_result, linked_result, edge_result = (MagicMock() for _ in range(3))
    root_result.scalars.return_value = [root]
    linked_result.scalars.return_value = []
    edge_result.scalars.return_value = [
        SimpleNamespace(source_object_id=f"source-{index}", target_object_id=root.id)
        for index in range(MAX_COMPILED_OBJECTS + 1)
    ]
    db.execute.side_effect = [root_result, linked_result, edge_result]

    with pytest.raises(ContextSelectionError) as error:
        await WorkspaceContextCompiler(db).compile("aura", [root.id])

    assert error.value.details["object_limit"] == MAX_COMPILED_OBJECTS
    assert db.execute.await_count == 3



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
async def test_personal_notes_persist_once_and_project_links_share_the_same_graph_object(async_client):
    created = await async_client.post("/v1/workspace/notes", json={
        "title": "Shared migration note",
        "body": "Preserve the rollback path.",
        "tags": ["migration", "migration"],
        "project_names": ["aura", "transportability"],
        "pinned": True,
    })
    assert created.status_code == 201
    note = created.json()
    assert note["tags"] == ["migration"]
    assert note["pinned"] is True
    assert note["project_names"] == ["aura", "transportability"]

    personal_notes = (await async_client.get("/v1/workspace/notes")).json()
    assert [item["id"] for item in personal_notes] == [note["id"]]
    for project_name in note["project_names"]:
        graph = (await async_client.get(f"/v1/workspace/projects/{project_name}/graph")).json()
        linked = next(item for item in graph["objects"] if item["id"] == note["id"])
        assert linked["project_name"] is None
        assert linked["content"] == "Preserve the rollback path."

    board_edit = await async_client.put(f"/v1/workspace/projects/aura/objects/{note['id']}", json={
        "title": "Shared migration note",
        "content": "Preserve the rollback path.",
        "metadata_json": {"privacy_policy": "local_only", "tags": ["migration"], "pinned": True},
    })
    assert board_edit.status_code == 200

    updated = await async_client.put(f"/v1/workspace/notes/{note['id']}", json={
        "title": "Updated shared note",
        "body": "Keep exact user-authored text.",
        "tags": ["decision"],
        "project_names": ["aura"],
        "pinned": False,
    })
    assert updated.status_code == 200
    assert updated.json()["project_names"] == ["aura"]
    aura_graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    transport_graph = (await async_client.get("/v1/workspace/projects/transportability/graph")).json()
    linked_note = next(item for item in aura_graph["objects"] if item["id"] == note["id"])
    assert linked_note["content"] == "Keep exact user-authored text."
    assert linked_note["metadata_json"]["privacy_policy"] == "local_only"
    assert note["id"] not in {item["id"] for item in transport_graph["objects"]}


@pytest.mark.asyncio
async def test_project_context_can_select_a_personal_note_and_board_delete_only_unlinks(async_client):
    from app.models.base import ModelRole
    from app.models.router import model_router

    created = await async_client.post("/v1/workspace/notes", json={
        "title": "Deployment constraint",
        "body": "Keep the migration reversible.",
        "project_names": ["aura"],
    })
    assert created.status_code == 201
    note_id = created.json()["id"]
    board_edit = await async_client.put(f"/v1/workspace/projects/aura/objects/{note_id}", json={
        "title": "Deployment constraint",
        "content": "Keep the migration reversible.",
        "metadata_json": {"privacy_policy": "local_only"},
    })
    assert board_edit.status_code == 200
    response = await async_client.post("/v1/chat", json={
        "session_id": "personal-note-context-session",
        "project_name": "aura",
        "message": "Plan the rollout.",
        "context_object_ids": [note_id],
    })
    assert response.status_code == 200
    request = model_router.get_provider("mock").call_history[-1]
    system_message = next(message for message in request.messages if message.role == ModelRole.SYSTEM)
    assert note_id in system_message.content
    assert "Keep the migration reversible." in system_message.content

    call_count = len(model_router.get_provider("mock").call_history)
    blocked = await async_client.post("/v1/chat", json={
        "session_id": "personal-note-cloud-boundary-session",
        "project_name": "aura",
        "message": "This local note must remain local.",
        "model_override": "openai:gpt-4o",
        "context_object_ids": [note_id],
    })
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == call_count

    unlinked = await async_client.post("/v1/workspace/notes", json={
        "title": "Another personal note",
        "body": "Not linked to this project.",
    })
    rejected_selection = await async_client.post("/v1/chat", json={
        "session_id": "unlinked-personal-note-context-session",
        "project_name": "aura",
        "message": "Do not include an unlinked note.",
        "context_object_ids": [unlinked.json()["id"]],
    })
    assert rejected_selection.status_code == 422
    assert rejected_selection.json()["code"] == "ContextSelectionError"
    assert len(model_router.get_provider("mock").call_history) == call_count

    local_note = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note", "title": "Project note", "content": "Project-local object.",
    })
    relation = await async_client.post("/v1/workspace/projects/aura/edges", json={
        "source_object_id": note_id,
        "target_object_id": local_note.json()["id"],
        "relation_type": "related_to",
        "edge_family": "semantic",
    })
    assert relation.status_code == 201

    deleted_from_project = await async_client.delete(f"/v1/workspace/projects/aura/objects/{note_id}")
    assert deleted_from_project.status_code == 204
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert note_id not in {item["id"] for item in graph["objects"]}
    assert note_id not in {object_id for edge in graph["edges"] for object_id in (edge["source_object_id"], edge["target_object_id"])}
    remaining_notes = (await async_client.get("/v1/workspace/notes")).json()
    assert note_id in {item["id"] for item in remaining_notes}


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
    assert selected_model["payload"]["requires_vision"] is False
    assert selected_model["payload"]["required_capabilities"] == []
    assert selected_model["payload"]["estimated_input_tokens"] > 0
    assert selected_model["payload"]["reserved_output_tokens"] == 2048

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
async def test_merged_continuation_compiles_destination_branch_and_selected_context(async_client):
    from app.models.router import model_router
    from app.models.base import ModelRole

    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Selected constraint",
        "content": "Keep the migration reversible.",
    })
    destination = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "conversation_branch",
        "title": "Existing destination branch",
        "content": "The branch is investigating rollout sequencing.",
    })
    assert source.status_code == destination.status_code == 201

    merged = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "conversation_branch",
        "title": "Merged continuation from Existing destination branch",
        "metadata_json": {"merged_into_branch_id": destination.json()["id"]},
        "source_object_ids": [destination.json()["id"], source.json()["id"]],
    })
    assert merged.status_code == 201

    response = await async_client.post("/v1/chat", json={
        "session_id": "merged-continuation-context-session",
        "project_name": "aura",
        "message": "Continue with this merged context.",
        "context_object_ids": [merged.json()["id"]],
    })
    assert response.status_code == 200

    request = model_router.get_provider("mock").call_history[-1]
    system_message = next(message for message in request.messages if message.role == ModelRole.SYSTEM)
    assert "Keep the migration reversible." in system_message.content
    assert "The branch is investigating rollout sequencing." in system_message.content
    assert "Merged continuation from Existing destination branch" in system_message.content

    run = (await async_client.get(f"/v1/runs/{response.json()['run_id']}" )).json()
    compiled_event = next(event for event in run["events"] if event["event_type"] == "context_compiled")
    compiled_objects = compiled_event["payload"]["objects"]
    assert {item["object_id"] for item in compiled_objects} == {
        source.json()["id"], destination.json()["id"], merged.json()["id"],
    }
    assert next(item for item in compiled_objects if item["object_id"] == merged.json()["id"])["selected_by_user"] is True


@pytest.mark.asyncio
async def test_chat_task_type_selects_the_assigned_profile_task_route(async_client):
    profile = await async_client.post("/v1/routing/profiles", json={
        "name": "Task route integration",
        "routes": {
            "root": {"model_override": "mock:mock-default"},
            "coding": {"model_override": "mock:mock-pro"},
            "writing": {"model_override": "mock:mock-fast"},
        },
    })
    assert profile.status_code == 201
    profile_id = profile.json()["id"]
    assignment = await async_client.post(f"/v1/routing/assignments/aura?profile_id={profile_id}")
    assert assignment.status_code == 200

    response = await async_client.post("/v1/chat", json={
        "session_id": "coding-task-route-session",
        "project_name": "aura",
        "message": "Review this code change.",
        "task_type": "coding",
    })
    assert response.status_code == 200

    run = (await async_client.get(f"/v1/runs/{response.json()['run_id']}")).json()
    selected = next(event for event in run["events"] if event["event_type"] == "model_selected")
    assert selected["payload"]["task_type"] == "coding"
    assert selected["payload"]["model"] == "mock-pro"
    assert selected["payload"]["profile_id"] == profile_id


@pytest.mark.asyncio
async def test_user_workspace_object_can_be_restored_with_its_stable_id(async_client):
    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note", "title": "Undo source", "content": "Keep this exact source."
    })
    object_id = "11111111-1111-4111-8111-111111111111"
    created = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "id": object_id,
        "object_type": "context_bridge",
        "title": "Restorable handoff",
        "content": "Selected only.",
        "source_object_ids": [source.json()["id"]],
    })
    assert created.status_code == 201
    assert created.json()["id"] == object_id

    deleted = await async_client.delete(f"/v1/workspace/projects/aura/objects/{object_id}")
    assert deleted.status_code == 204

    restored = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "id": object_id,
        "object_type": "context_bridge",
        "title": "Restorable handoff",
        "content": "Selected only.",
        "source_object_ids": [source.json()["id"]],
    })
    assert restored.status_code == 201
    assert restored.json()["id"] == object_id
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert any(edge["target_object_id"] == object_id and edge["relation_type"] == "bridges_to" for edge in graph["edges"])


@pytest.mark.asyncio
async def test_known_model_context_window_blocks_before_provider_invocation(async_client):
    from app.models.router import model_router

    metadata = model_router.get_provider_metadata("mock")
    assert metadata is not None
    previous_window = metadata.context_window
    model = metadata.default_model
    previous_model_window = metadata.model_context_windows.get(model)
    metadata.context_window = 1
    metadata.model_context_windows[model] = 1
    calls_before = len(model_router.get_provider("mock").call_history)
    try:
        response = await async_client.post("/v1/chat", json={
            "session_id": "small-context-window-session",
            "message": "A quick request.",
            "model_override": f"mock:{model}",
        })
    finally:
        metadata.context_window = previous_window
        if previous_model_window is None:
            metadata.model_context_windows.pop(model, None)
        else:
            metadata.model_context_windows[model] = previous_model_window

    assert response.status_code == 422
    assert response.json()["code"] == "ModelCapabilityMismatch"
    assert "context window (1)" in response.json()["message"]
    assert len(model_router.get_provider("mock").call_history) == calls_before


@pytest.mark.asyncio
async def test_selected_context_capabilities_constrain_model_routing(async_client):
    from app.models.router import model_router

    object_response = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Image inspection requirement",
        "content": "The selected context requires image understanding.",
        "metadata_json": {"requires_vision": True},
    })
    assert object_response.status_code == 201
    object_id = object_response.json()["id"]
    calls_before = len(model_router.get_provider("mock").call_history)

    incapable = await async_client.post("/v1/chat", json={
        "session_id": "vision-context-incapable-session",
        "project_name": "aura",
        "message": "Analyze this context.",
        "model_override": "mock:mock-default",
        "context_object_ids": [object_id],
    })
    assert incapable.status_code == 422
    assert incapable.json()["code"] == "ModelCapabilityMismatch"
    assert len(model_router.get_provider("mock").call_history) == calls_before

    capable = await async_client.post("/v1/chat", json={
        "session_id": "vision-context-capable-session",
        "project_name": "aura",
        "message": "Analyze this context.",
        "model_override": "mock:mock-pro",
        "context_object_ids": [object_id],
    })
    assert capable.status_code == 200
    assert model_router.get_provider("mock").call_history[-1].selected_model == "mock-pro"


@pytest.mark.asyncio
async def test_selected_context_tool_requirement_survives_empty_tool_registry(async_client, monkeypatch):
    from app.models.router import model_router
    from app.tools.registry import tool_registry

    metadata = model_router.get_provider_metadata("mock")
    assert metadata is not None
    monkeypatch.setitem(metadata.tool_support, "mock-default", "unsupported")
    monkeypatch.setattr(tool_registry, "get_tool_definitions", lambda: [])

    selected = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Tool requirement",
        "content": "Use the project code graph before proposing changes.",
        "metadata_json": {"requires_tools": True},
    })
    assert selected.status_code == 201

    response = await async_client.post("/v1/chat", json={
        "session_id": "tool-context-empty-registry-session",
        "project_name": "aura",
        "message": "Inspect the selected context.",
        "context_object_ids": [selected.json()["id"]],
    })

    assert response.status_code == 200
    run = (await async_client.get(f"/v1/runs/{response.json()['run_id']}")).json()
    selected_model = next(event for event in run["events"] if event["event_type"] == "model_selected")
    assert selected_model["payload"]["requires_tools"] is True
    assert selected_model["payload"]["model"] != "mock-default"


@pytest.mark.asyncio
async def test_project_memory_local_only_blocks_cloud_model_before_provider_call(async_client, test_db_session):
    from app.memory.service import SQLMemoryService
    from app.models.router import model_router

    await SQLMemoryService(test_db_session).store_project_memory(
        "aura",
        "private-research",
        "This project's research must stay on-device.",
        metadata={"privacy_policy": "local_only"},
    )
    calls_before = len(model_router.get_provider("mock").call_history)

    response = await async_client.post("/v1/chat", json={
        "session_id": "project-memory-local-only-session",
        "project_name": "aura",
        "message": "Summarize my project memory.",
        "model_override": "openai:gpt-4o",
    })

    assert response.status_code == 403
    assert response.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before


@pytest.mark.asyncio
async def test_session_local_only_episode_blocks_cloud_model_before_provider_call(async_client, test_db_session):
    from app.memory.service import SQLMemoryService
    from app.models.router import model_router

    memory_service = SQLMemoryService(test_db_session)
    session = await memory_service.get_or_create_session("episode-local-only-session")
    await memory_service.record_episodic_memory(
        session.id,
        "This session's findings must stay on-device.",
        metadata={"privacy_policy": "local_only"},
    )
    calls_before = len(model_router.get_provider("mock").call_history)

    response = await async_client.post("/v1/chat", json={
        "session_id": session.id,
        "message": "Summarize this session.",
        "model_override": "openai:gpt-4o",
    })

    assert response.status_code == 403
    assert response.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before


@pytest.mark.asyncio
async def test_profile_local_only_blocks_cloud_model_before_provider_call(async_client, test_db_session):
    from app.memory.service import SQLMemoryService
    from app.models.router import model_router

    memory_service = SQLMemoryService(test_db_session)
    await memory_service.set_profile_fact(
        "private_preference",
        "This saved setting must stay on-device.",
        metadata={"privacy_policy": "local_only"},
    )
    calls_before = len(model_router.get_provider("mock").call_history)

    response = await async_client.post("/v1/chat", json={
        "session_id": "profile-local-only-session",
        "message": "Summarize my preferences.",
        "model_override": "openai:gpt-4o",
    })

    assert response.status_code == 403
    assert response.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before


@pytest.mark.asyncio
async def test_project_scoped_semantic_local_only_blocks_cloud_model_before_provider_call(async_client, test_db_session):
    from app.memory.service import SQLMemoryService
    from app.models.router import model_router

    semantic_fact = "AURA migration findings must remain on this device."
    await SQLMemoryService(test_db_session).store_semantic_memory(
        semantic_fact,
        project_name="aura",
        metadata={"privacy_policy": "local_only"},
    )
    calls_before = len(model_router.get_provider("mock").call_history)

    response = await async_client.post("/v1/chat", json={
        "session_id": "semantic-local-only-session",
        "project_name": "aura",
        "message": semantic_fact,
        "model_override": "openai:gpt-4o",
    })

    assert response.status_code == 403
    assert response.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before


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
