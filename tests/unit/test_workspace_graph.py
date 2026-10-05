"""Durable shared workspace graph API invariants."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.memory.service import SQLMemoryService
from app.db.models import MessageModel, RunEventModel, RunModel, SessionModel, WorkspaceEdgeModel, WorkspaceObjectModel
from app.core.errors import ContextSelectionError
from app.memory.context_compiler import MAX_COMPILED_OBJECTS, WorkspaceContextCompiler
from app.api.schemas import MAX_WORKSPACE_LAYOUT_BYTES, MAX_WORKSPACE_METADATA_BYTES, WorkspaceLayoutWrite, WorkspaceObjectCreate


def test_workspace_object_metadata_has_a_serialized_size_bound():
    accepted = WorkspaceObjectCreate(object_type="manual_note", metadata_json={"payload": "x" * (MAX_WORKSPACE_METADATA_BYTES - 32)})
    assert accepted.metadata_json["payload"]

    with pytest.raises(ValueError, match="metadata_json must be"):
        WorkspaceObjectCreate(object_type="manual_note", metadata_json={"payload": "x" * MAX_WORKSPACE_METADATA_BYTES})


def test_workspace_layout_has_a_serialized_size_bound_and_rejects_non_finite_values():
    accepted = WorkspaceLayoutWrite(layout={"payload": "x" * (MAX_WORKSPACE_LAYOUT_BYTES - 32)}, expected_revision=0)
    assert accepted.layout["payload"]

    with pytest.raises(ValueError, match="layout must be"):
        WorkspaceLayoutWrite(layout={"payload": "x" * MAX_WORKSPACE_LAYOUT_BYTES}, expected_revision=0)

    with pytest.raises(ValueError, match="finite JSON values"):
        WorkspaceLayoutWrite(layout={"zoom": float("nan")}, expected_revision=0)


@pytest.mark.asyncio
async def test_workspace_api_rejects_oversized_metadata_and_layout_before_persistence(async_client):
    object_response = await async_client.post(
        "/v1/workspace/projects/bounded-payload/objects",
        json={
            "object_type": "manual_note",
            "title": "must not persist",
            "metadata_json": {"payload": "x" * MAX_WORKSPACE_METADATA_BYTES},
        },
    )
    assert object_response.status_code == 422

    layout_response = await async_client.put(
        "/v1/workspace/projects/bounded-payload/layout",
        json={"layout": {"payload": "x" * MAX_WORKSPACE_LAYOUT_BYTES}, "expected_revision": 0},
    )
    assert layout_response.status_code == 422

    graph = await async_client.get("/v1/workspace/projects/bounded-payload/graph")
    assert graph.status_code == 200
    assert graph.json()["objects"] == []
    assert graph.json()["layout"]["revision"] == 0


@pytest.mark.asyncio
async def test_workspace_graph_paginates_objects_and_edges_with_stable_cursors(async_client):
    project_name = "graph-pagination"
    for title in ("First", "Second", "Third"):
        response = await async_client.post(
            f"/v1/workspace/projects/{project_name}/objects",
            json={"object_type": "manual_note", "title": title, "content": title},
        )
        assert response.status_code == 201

    complete = (await async_client.get(f"/v1/workspace/projects/{project_name}/graph")).json()
    object_ids = [item["id"] for item in complete["objects"]]
    for source_id, target_id in zip(object_ids, object_ids[1:]):
        edge = await async_client.post(
            f"/v1/workspace/projects/{project_name}/edges",
            json={
                "source_object_id": source_id,
                "target_object_id": target_id,
                "relation_type": "related_to",
                "edge_family": "semantic",
            },
        )
        assert edge.status_code == 201

    complete = (await async_client.get(f"/v1/workspace/projects/{project_name}/graph")).json()

    first = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={"object_page_size": 2, "edge_page_size": 1},
    )
    assert first.status_code == 200
    first_page = first.json()
    assert [item["id"] for item in first_page["objects"]] == object_ids[:2]
    assert first_page["objects_next_cursor"]
    assert len(first_page["edges"]) == 1
    assert first_page["edges_next_cursor"]
    assert first_page["layout"]["revision"] == 0

    second = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={
            "object_page_size": 2,
            "object_cursor": first_page["objects_next_cursor"],
            "edge_page_size": 1,
            "edge_cursor": first_page["edges_next_cursor"],
            "include_project_state": "false",
        },
    )
    assert second.status_code == 200
    second_page = second.json()
    assert [item["id"] for item in second_page["objects"]] == object_ids[2:]
    assert second_page["objects_next_cursor"] is None
    assert second_page["edges_next_cursor"] is None
    assert len(second_page["edges"]) == 1
    assert second_page["execution_traces"] == []

    newest_edge_page = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={"object_page_size": 1, "objects_exhausted": "true", "edge_page_size": 1, "newest_first": "true", "include_project_state": "false"},
    )
    newest_edges = newest_edge_page.json()
    newest_edge_ids = [item["id"] for item in reversed(complete["edges"])]
    assert [item["id"] for item in newest_edges["edges"]] == newest_edge_ids[:1]
    assert newest_edges["edges_next_cursor"]
    older_edge_page = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={
            "object_page_size": 1,
            "objects_exhausted": "true",
            "edge_page_size": 1,
            "edge_cursor": newest_edges["edges_next_cursor"],
            "newest_first": "true",
            "include_project_state": "false",
        },
    )
    assert [item["id"] for item in older_edge_page.json()["edges"]] == newest_edge_ids[1:]


@pytest.mark.asyncio
async def test_workspace_graph_can_page_newest_objects_before_older_objects(async_client):
    project_name = "newest-graph-pagination"
    for title in ("First", "Second", "Third", "Fourth", "Fifth"):
        response = await async_client.post(
            f"/v1/workspace/projects/{project_name}/objects",
            json={"object_type": "manual_note", "title": title, "content": title},
        )
        assert response.status_code == 201

    all_objects = (await async_client.get(f"/v1/workspace/projects/{project_name}/graph")).json()["objects"]
    newest = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={"object_page_size": 2, "newest_first": "true", "edges_exhausted": "true", "include_project_state": "false"},
    )
    assert newest.status_code == 200
    first_page = newest.json()
    assert [item["id"] for item in first_page["objects"]] == [item["id"] for item in reversed(all_objects)][:2]
    assert first_page["objects_next_cursor"]
    assert first_page["edges"] == []
    assert first_page["execution_traces"] == []

    older = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={
            "object_page_size": 2,
            "newest_first": "true",
            "object_cursor": first_page["objects_next_cursor"],
            "edges_exhausted": "true",
            "include_project_state": "false",
        },
    )
    assert [item["id"] for item in older.json()["objects"]] == [item["id"] for item in reversed(all_objects)][2:4]


@pytest.mark.asyncio
async def test_workspace_graph_filters_object_types_and_edge_families_before_pagination(async_client, test_db_session):
    project_name = "research-graph-filter"
    created_at = datetime.now(timezone.utc)
    objects = [
        WorkspaceObjectModel(id="research-claim-new", project_name=project_name, object_type="research_claim", created_by="research", title="New claim", content="", metadata_json={}, created_at=created_at, updated_at=created_at),
        WorkspaceObjectModel(id="research-claim-old", project_name=project_name, object_type="research_claim", created_by="research", title="Old claim", content="", metadata_json={}, created_at=created_at - timedelta(seconds=1), updated_at=created_at - timedelta(seconds=1)),
        WorkspaceObjectModel(id="research-chat", project_name=project_name, object_type="conversation_turn", created_by="assistant", title="Chat turn", content="", metadata_json={}, created_at=created_at + timedelta(seconds=1), updated_at=created_at + timedelta(seconds=1)),
    ]
    test_db_session.add_all(objects)
    test_db_session.add_all([
        WorkspaceEdgeModel(id="research-provenance-edge", project_name=project_name, source_object_id="research-claim-new", target_object_id="research-claim-old", relation_type="supports_claim", edge_family="provenance", created_by="research", metadata_json={}, created_at=created_at),
        WorkspaceEdgeModel(id="research-semantic-edge", project_name=project_name, source_object_id="research-claim-new", target_object_id="research-claim-old", relation_type="related_to", edge_family="semantic", created_by="user", metadata_json={}, created_at=created_at + timedelta(seconds=1)),
    ])
    await test_db_session.commit()

    first_response = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={"object_types": ["research_claim", "research_evidence"], "edge_families": ["provenance"], "object_page_size": 1, "newest_first": "true", "include_project_state": "false"},
    )
    assert first_response.status_code == 200
    first = first_response.json()
    assert [item["id"] for item in first["objects"]] == ["research-claim-new"]
    assert [edge["id"] for edge in first["edges"]] == ["research-provenance-edge"]
    assert first["objects_next_cursor"]

    second_response = await async_client.get(
        f"/v1/workspace/projects/{project_name}/graph",
        params={"object_types": ["research_claim", "research_evidence"], "edge_families": ["provenance"], "object_page_size": 1, "newest_first": "true", "object_cursor": first["objects_next_cursor"], "edges_exhausted": "true", "include_project_state": "false"},
    )
    assert second_response.status_code == 200
    assert [item["id"] for item in second_response.json()["objects"]] == ["research-claim-old"]


@pytest.mark.asyncio
async def test_workspace_graph_rejects_unknown_edge_family_filter(async_client):
    response = await async_client.get(
        "/v1/workspace/projects/research-graph-filter/graph",
        params={"edge_families": "invented"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unsupported workspace edge family filter."


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor_name", ["object_cursor", "edge_cursor"])
@pytest.mark.parametrize("cursor", ["not-a-cursor", ""])
async def test_workspace_graph_rejects_invalid_cursor(async_client, cursor_name, cursor):
    response = await async_client.get(
        "/v1/workspace/projects/cursor-validation/graph",
        params={cursor_name: cursor},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid pagination cursor."


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
async def test_selected_context_is_persisted_as_conversation_ancestry(async_client, test_db_session):
    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Branch constraint",
        "content": "Keep branch decisions explicit.",
    })
    assert source.status_code == 201

    response = await async_client.post("/v1/chat", json={
        "session_id": "context-ancestry-session",
        "project_name": "aura",
        "message": "Continue from the selected branch context.",
        "context_object_ids": [source.json()["id"]],
    })
    assert response.status_code == 200

    from sqlalchemy import select
    from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel

    user_turn = await test_db_session.scalar(
        select(WorkspaceObjectModel).where(
            WorkspaceObjectModel.source_message_id == response.json()["user_message_id"]
        )
    )
    assert user_turn is not None
    [context_edge] = list((await test_db_session.execute(
        select(WorkspaceEdgeModel).where(
            WorkspaceEdgeModel.project_name == "aura",
            WorkspaceEdgeModel.source_object_id == source.json()["id"],
            WorkspaceEdgeModel.target_object_id == user_turn.id,
            WorkspaceEdgeModel.relation_type == "context_used",
            WorkspaceEdgeModel.edge_family == "context",
        )
    )).scalars())

    compiled = await WorkspaceContextCompiler(test_db_session).compile("aura", [user_turn.id])
    assert {item.object_id for item in compiled.objects} == {source.json()["id"], user_turn.id}
    assert "Keep branch decisions explicit." in compiled.prompt_text
    assert "Continue from the selected branch context." in compiled.prompt_text


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
        json={"title": "Source edited", "content": "Keep exact wording, edited by the user.", "metadata_json": {}, "expected_revision": source.json()["revision"]},
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
        "privacy_policy": "confidential",
    })
    assert created.status_code == 201
    note = created.json()
    assert note["tags"] == ["migration"]
    assert note["pinned"] is True
    assert note["privacy_policy"] == "confidential"
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
        "expected_revision": note["revision"],
    })
    assert board_edit.status_code == 200

    updated = await async_client.put(f"/v1/workspace/notes/{note['id']}", json={
        "title": "Updated shared note",
        "body": "Keep exact user-authored text.",
        "tags": ["decision"],
        "project_names": ["aura"],
        "pinned": False,
        "expected_revision": board_edit.json()["revision"],
    })
    assert updated.status_code == 200
    assert updated.json()["project_names"] == ["aura"]
    aura_graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    transport_graph = (await async_client.get("/v1/workspace/projects/transportability/graph")).json()
    linked_note = next(item for item in aura_graph["objects"] if item["id"] == note["id"])
    assert linked_note["content"] == "Keep exact user-authored text."
    assert linked_note["metadata_json"]["privacy_policy"] == "local_only"
    assert updated.json()["privacy_policy"] == "local_only"

    cleared = await async_client.put(f"/v1/workspace/notes/{note['id']}", json={
        "title": "Updated shared note",
        "body": "Keep exact user-authored text.",
        "tags": ["decision"],
        "project_names": ["aura"],
        "pinned": False,
        "privacy_policy": None,
        "expected_revision": updated.json()["revision"],
    })
    assert cleared.status_code == 200
    assert cleared.json()["privacy_policy"] is None
    aura_graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    linked_note = next(item for item in aura_graph["objects"] if item["id"] == note["id"])
    assert "privacy_policy" not in linked_note["metadata_json"]
    assert note["id"] not in {item["id"] for item in transport_graph["objects"]}


@pytest.mark.asyncio
async def test_personal_note_delete_checks_revision_and_cascades_project_links(async_client):
    created = await async_client.post("/v1/workspace/notes", json={
        "title": "Retired deployment note",
        "body": "Remove after the migration is complete.",
        "project_names": ["aura", "transportability"],
    })
    assert created.status_code == 201
    note = created.json()

    stale_delete = await async_client.delete(
        f"/v1/workspace/notes/{note['id']}?expected_revision={note['revision'] + 1}"
    )
    assert stale_delete.status_code == 409
    assert stale_delete.json()["detail"]["current_revision"] == note["revision"]
    assert note["id"] in {item["id"] for item in (await async_client.get("/v1/workspace/notes")).json()}

    deleted = await async_client.delete(
        f"/v1/workspace/notes/{note['id']}?expected_revision={note['revision']}"
    )
    assert deleted.status_code == 204
    assert note["id"] not in {item["id"] for item in (await async_client.get("/v1/workspace/notes")).json()}
    for project_name in note["project_names"]:
        graph = (await async_client.get(f"/v1/workspace/projects/{project_name}/graph")).json()
        assert note["id"] not in {item["id"] for item in graph["objects"]}
        assert note["id"] not in {object_id for edge in graph["edges"] for object_id in (edge["source_object_id"], edge["target_object_id"])}


@pytest.mark.asyncio
async def test_personal_note_delete_does_not_delete_project_local_objects(async_client):
    created = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Project-local note",
        "content": "Keep project scope.",
    })
    assert created.status_code == 201
    item = created.json()

    response = await async_client.delete(f"/v1/workspace/notes/{item['id']}?expected_revision=1")

    assert response.status_code == 404
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert item["id"] in {obj["id"] for obj in graph["objects"]}


@pytest.mark.asyncio
async def test_workspace_object_revisions_reject_stale_board_and_notes_updates(async_client):
    created = await async_client.post("/v1/workspace/notes", json={
        "title": "Shared note",
        "body": "Original body",
        "project_names": ["aura"],
    })
    assert created.status_code == 201
    note = created.json()
    assert note["revision"] == 1

    board_update = await async_client.put(f"/v1/workspace/projects/aura/objects/{note['id']}", json={
        "title": "Shared note",
        "content": "Updated from the Board",
        "metadata_json": {},
        "expected_revision": note["revision"],
    })
    assert board_update.status_code == 200
    assert board_update.json()["revision"] == 2

    stale_note_update = await async_client.put(f"/v1/workspace/notes/{note['id']}", json={
        "title": "Shared note",
        "body": "Stale Notes tab content",
        "project_names": ["aura"],
        "expected_revision": note["revision"],
    })
    assert stale_note_update.status_code == 409
    assert stale_note_update.json()["detail"]["current_revision"] == 2

    stale_board_update = await async_client.put(f"/v1/workspace/projects/aura/objects/{note['id']}", json={
        "title": "Shared note",
        "content": "Stale Board tab content",
        "metadata_json": {},
        "expected_revision": note["revision"],
    })
    assert stale_board_update.status_code == 409
    assert stale_board_update.json()["detail"]["current_revision"] == 2

    current_graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    current_note = next(item for item in current_graph["objects"] if item["id"] == note["id"])
    assert current_note["content"] == "Updated from the Board"
    assert current_note["revision"] == 2


@pytest.mark.asyncio
async def test_workspace_object_update_requires_an_expected_revision(async_client):
    created = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Revision-required note",
        "content": "Original body",
    })
    assert created.status_code == 201
    response = await async_client.put(f"/v1/workspace/projects/aura/objects/{created.json()['id']}", json={
        "title": "Revision-required note",
        "content": "New body",
        "metadata_json": {},
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_workspace_summary_counts_saved_and_project_linked_collections(async_client):
    note = await async_client.post("/v1/workspace/notes", json={
        "title": "Linked note", "body": "Note body", "project_names": ["aura"],
    })
    await async_client.post("/v1/workspace/notes", json={"title": "Personal note", "body": "Private"})
    linked_file = await async_client.post("/v1/workspace/library", json={
        "name": "linked.pdf", "kind": "PDF", "collection": "Research", "project_names": ["aura"],
    })
    await async_client.post("/v1/workspace/library", json={
        "name": "personal.pdf", "kind": "PDF", "collection": "Books", "project_names": [],
    })
    assert note.status_code == 201
    assert linked_file.status_code == 201

    global_summary = await async_client.get("/v1/workspace/summary")
    project_summary = await async_client.get("/v1/workspace/summary", params={"project_name": "aura"})

    assert global_summary.status_code == 200
    assert global_summary.json() == {
        "note_count": 2,
        "library_count": 2,
        "linked_library_count": 1,
        "project_name": None,
        "project_note_count": 0,
        "project_library_count": 0,
    }
    assert project_summary.json()["project_name"] == "aura"
    assert project_summary.json()["project_note_count"] == 1
    assert project_summary.json()["project_library_count"] == 1


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
        "expected_revision": created.json()["revision"],
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
        "session_id": "note-cloud-boundary",
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
        "session_id": "unlinked-note-context",
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
        json={"layout": {"positions": {note_id: {"x": 12, "y": 34}}, "densities": {note_id: "compact"}, "viewport": {"zoom": 0.8}}, "expected_revision": 0},
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert saved.json()["layout"]["positions"][note_id] == {"x": 12, "y": 34}

    stale = await async_client.put(
        "/v1/workspace/projects/aura/layout",
        json={"layout": {"nodes": {}}, "expected_revision": 0},
    )
    assert stale.status_code == 409
    assert (await async_client.get("/v1/workspace/projects/aura/graph")).json()["layout"]["revision"] == 1

    partial_layout = await async_client.put(
        "/v1/workspace/projects/aura/layout",
        json={"expected_revision": 1, "layout": {"positions": {"new": {"x": 80, "y": 90}}, "densities": {"new": "full"}, "viewport": {"x": 5, "y": 6, "zoom": 1}}},
    )
    assert partial_layout.status_code == 200
    assert partial_layout.json()["layout"]["positions"] == {note_id: {"x": 12, "y": 34}, "new": {"x": 80, "y": 90}}
    assert partial_layout.json()["layout"]["densities"] == {note_id: "compact", "new": "full"}
    loaded_layout = await async_client.get("/v1/workspace/projects/aura/layout")
    assert loaded_layout.status_code == 200
    assert loaded_layout.json()["revision"] == 2
    assert loaded_layout.json()["layout"] == partial_layout.json()["layout"]


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
async def test_context_compiler_follows_full_session_branch_ancestry(test_db_session):
    from sqlalchemy import select
    from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel

    service = SQLMemoryService(test_db_session)
    session = await service.get_or_create_session("branch-ancestry-session")
    history = [
        ("user", "First question"),
        ("assistant", "First answer"),
        ("user", "Second question"),
        ("assistant", "Second answer"),
    ]
    messages = [await service.save_message(session.id, role, content) for role, content in history]

    await service.attach_session_to_project(session.id, "aura")
    await service.attach_session_to_project(session.id, "aura")

    objects = list((await test_db_session.execute(
        select(WorkspaceObjectModel).where(WorkspaceObjectModel.source_message_id.in_([message.id for message in messages]))
    )).scalars())
    object_by_message = {item.source_message_id: item for item in objects}
    # Keep this fixture independent of timestamp precision and UUID ordering.
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, message in enumerate(messages):
        message.created_at = base_time + timedelta(seconds=index)
        object_by_message[message.id].created_at = base_time + timedelta(seconds=index)
    await test_db_session.commit()
    continuations = list((await test_db_session.execute(
        select(WorkspaceEdgeModel).where(
            WorkspaceEdgeModel.project_name == "aura",
            WorkspaceEdgeModel.relation_type == "continues",
        )
    )).scalars())
    assert len(continuations) == 1
    assert continuations[0].created_by == "system"
    assert continuations[0].edge_family == "context"

    second_answer = messages[-1]
    compiled = await WorkspaceContextCompiler(test_db_session).compile(
        "aura", [object_by_message[second_answer.id].id]
    )
    for _role, content in history:
        assert content in compiled.prompt_text

    live_user = await service.save_message(session.id, "user", "Third question")
    live_answer = await service.save_message(session.id, "assistant", "Third answer")
    live_objects = list((await test_db_session.execute(
        select(WorkspaceObjectModel).where(WorkspaceObjectModel.source_message_id.in_([live_user.id, live_answer.id]))
    )).scalars())
    live_object_by_message = {item.source_message_id: item for item in live_objects}
    live_object_by_message[live_user.id].created_at = base_time + timedelta(seconds=len(messages))
    live_object_by_message[live_answer.id].created_at = base_time + timedelta(seconds=len(messages) + 1)
    await test_db_session.commit()
    live_answer_object = next(item for item in live_objects if item.source_message_id == live_answer.id)

    latest = await WorkspaceContextCompiler(test_db_session).compile("aura", [live_answer_object.id])
    for content in [*(content for _role, content in history), "Third question", "Third answer"]:
        assert content in latest.prompt_text
    all_continuations = list((await test_db_session.execute(
        select(WorkspaceEdgeModel).where(
            WorkspaceEdgeModel.project_name == "aura",
            WorkspaceEdgeModel.relation_type == "continues",
        )
    )).scalars())
    assert len(all_continuations) == 2


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
            "bridge_options": {"conclusions": True, "observations": False, "failed": False, "artifacts": True, "constraints": True, "decisions": True},
            "bridge_sections": {
                "conclusions": "Deploy in reversible stages.",
                "observations": "Disabled observation must stay out.",
                "failed": "",
                "artifacts": "Migration checklist v2.",
                "constraints": "Keep legacy clients working.",
                "decisions": "Roll back on a privacy breach.",
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
    assert "Keep legacy clients working." in system_message.content
    assert "Roll back on a privacy breach." in system_message.content
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
            "constraints": True,
            "decisions": True,
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
        RunEventModel(id="trace-research-failure", run_id=run.id, event_type="tool_executed", payload={
            "tool": "research_search", "result": {
                "success": False,
                "metadata": {
                    "error_code": "research_providers_unavailable",
                    "failed_providers": ["Semantic Scholar", "arXiv", "Crossref", "untrusted provider"],
                    "query": "private research query",
                },
            },
        }),
        RunEventModel(id="trace-research-success", run_id=run.id, event_type="tool_executed", payload={
            "tool": "research_search", "result": {
                "success": True,
                "metadata": {
                    "error_code": "research_providers_unavailable",
                    "failed_providers": ["Semantic Scholar"],
                },
            },
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
    assert [event["event_type"] for event in trace["events"]] == [
        "model_selected", "tool_requested", "tool_executed", "tool_executed", "tool_executed",
    ]
    tool_result = next(event for event in trace["events"] if event["event_type"] == "tool_executed" and event.get("tool_name") == "workspace.read")
    assert tool_result["tool_name"] == "workspace.read"
    assert tool_result["success"] is True
    research_failure = next(event for event in trace["events"] if event["error_code"] == "research_providers_unavailable")
    assert research_failure["success"] is False
    assert research_failure["failed_providers"] == ["Semantic Scholar", "arXiv", "Crossref"]
    research_success = next(
        event for event in trace["events"]
        if event["event_type"] == "tool_executed" and event["success"] is True and event.get("tool_name") == "research_search"
    )
    assert research_success["error_code"] is None
    assert research_success["failed_providers"] == []
    serialized = response.text
    for private_value in (
        "private prompt secret", "secret/path.txt", "private tool output secret", "never expose",
        "private research query", "untrusted provider",
    ):
        assert private_value not in serialized


@pytest.mark.asyncio
async def test_workspace_edges_cannot_forge_execution_or_provenance(async_client):
    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note", "title": "Source", "content": "User-authored source.",
    })
    target = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note", "title": "Target", "content": "User-authored target.",
    })
    source_id, target_id = source.json()["id"], target.json()["id"]

    for family in ("execution", "provenance"):
        created = await async_client.post("/v1/workspace/projects/aura/edges", json={
            "source_object_id": source_id,
            "target_object_id": target_id,
            "relation_type": "fabricated",
            "edge_family": family,
        })
        assert created.status_code == 422

        restored = await async_client.post(
            "/v1/workspace/projects/aura/edges/batch-restore",
            json={"edges": [{
                "id": "30000000-0000-4000-8000-000000000099",
                "source_object_id": source_id,
                "target_object_id": target_id,
                "relation_type": "fabricated",
                "edge_family": family,
            }]},
        )
        assert restored.status_code == 422

    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert graph["edges"] == []


@pytest.mark.asyncio
async def test_workspace_edge_deletion_preserves_system_edges_and_batches_atomically(
    async_client,
    test_db_session,
):
    from app.db.models import WorkspaceEdgeModel

    created = []
    for title in ("Edge source", "Edge target", "Edge third"):
        response = await async_client.post("/v1/workspace/projects/aura/objects", json={
            "object_type": "manual_note",
            "title": title,
            "content": title,
        })
        assert response.status_code == 201
        created.append(response.json()["id"])

    user_edges = []
    for source_id, target_id in ((created[0], created[1]), (created[1], created[2])):
        response = await async_client.post("/v1/workspace/projects/aura/edges", json={
            "source_object_id": source_id,
            "target_object_id": target_id,
            "relation_type": "related_to",
            "edge_family": "semantic",
        })
        assert response.status_code == 201
        user_edges.append(response.json()["id"])

    system_edge = WorkspaceEdgeModel(
        id="30000000-0000-4000-8000-000000000001",
        project_name="aura",
        source_object_id=created[0],
        target_object_id=created[2],
        relation_type="reply",
        edge_family="context",
        created_by="system",
    )
    test_db_session.add(system_edge)
    await test_db_session.commit()

    protected_single = await async_client.delete(
        f"/v1/workspace/projects/aura/edges/{system_edge.id}"
    )
    assert protected_single.status_code == 409

    mixed_batch = await async_client.request(
        "DELETE",
        "/v1/workspace/projects/aura/edges",
        json={"edge_ids": [user_edges[0], system_edge.id]},
    )
    assert mixed_batch.status_code == 409
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    remaining_ids = {edge["id"] for edge in graph["edges"]}
    assert set(user_edges) <= remaining_ids
    assert system_edge.id in remaining_ids

    deleted_batch = await async_client.request(
        "DELETE",
        "/v1/workspace/projects/aura/edges",
        json={"edge_ids": [user_edges[0]]},
    )
    assert deleted_batch.status_code == 204
    deleted_single = await async_client.delete(
        f"/v1/workspace/projects/aura/edges/{user_edges[1]}"
    )
    assert deleted_single.status_code == 204

    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    assert [edge["id"] for edge in graph["edges"]] == [system_edge.id]


@pytest.mark.asyncio
async def test_workspace_edge_batch_restore_preserves_ids_and_rejects_invalid_batches_atomically(async_client):
    object_ids = []
    for title in ("Restore source", "Restore target", "Restore third"):
        response = await async_client.post("/v1/workspace/projects/aura/objects", json={
            "object_type": "manual_note",
            "title": title,
            "content": title,
        })
        assert response.status_code == 201
        object_ids.append(response.json()["id"])

    created = await async_client.post("/v1/workspace/projects/aura/edges", json={
        "source_object_id": object_ids[0],
        "target_object_id": object_ids[1],
        "relation_type": "related_to",
        "edge_family": "semantic",
        "metadata_json": {"label": "stable"},
    })
    assert created.status_code == 201
    edge = created.json()
    deleted = await async_client.request(
        "DELETE",
        "/v1/workspace/projects/aura/edges",
        json={"edge_ids": [edge["id"]]},
    )
    assert deleted.status_code == 204

    restored = await async_client.post(
        "/v1/workspace/projects/aura/edges/batch-restore",
        json={"edges": [{
            "id": edge["id"],
            "source_object_id": edge["source_object_id"],
            "target_object_id": edge["target_object_id"],
            "relation_type": edge["relation_type"],
            "edge_family": edge["edge_family"],
            "metadata_json": edge["metadata_json"],
        }]},
    )
    assert restored.status_code == 201
    assert restored.json()[0]["id"] == edge["id"]
    assert restored.json()[0]["created_by"] == "user"
    assert restored.json()[0]["metadata_json"] == {"label": "stable"}

    context = await async_client.post("/v1/workspace/projects/aura/edges", json={
        "source_object_id": object_ids[0],
        "target_object_id": object_ids[1],
        "relation_type": "bridges_to",
        "edge_family": "context",
    })
    assert context.status_code == 201

    invalid_batch = await async_client.post(
        "/v1/workspace/projects/aura/edges/batch-restore",
        json={"edges": [
            {
                "id": "40000000-0000-4000-8000-000000000001",
                "source_object_id": object_ids[1],
                "target_object_id": object_ids[0],
                "relation_type": "bridges_to",
                "edge_family": "context",
            },
            {
                "id": "40000000-0000-4000-8000-000000000002",
                "source_object_id": object_ids[2],
                "target_object_id": object_ids[0],
                "relation_type": "related_to",
                "edge_family": "semantic",
            },
        ]},
    )
    assert invalid_batch.status_code == 409
    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    graph_ids = {item["id"] for item in graph["edges"]}
    assert edge["id"] in graph_ids
    assert context.json()["id"] in graph_ids
    assert "40000000-0000-4000-8000-000000000001" not in graph_ids
    assert "40000000-0000-4000-8000-000000000002" not in graph_ids


@pytest.mark.asyncio
async def test_context_bridge_inherits_privacy_through_omitted_context_set_ancestry(async_client):
    from app.models.router import model_router

    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Private source",
        "content": "Private source body must not be copied into the Bridge.",
        "metadata_json": {"privacy_policy": "local_only"},
    })
    assert source.status_code == 201
    context_set = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "context_set",
        "title": "Nested context set",
        "content": "",
        "metadata_json": {"privacy_policy": "public"},
        "source_object_ids": [source.json()["id"]],
    })
    assert context_set.status_code == 201
    bridge = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "context_bridge",
        "title": "Reviewed handoff",
        "content": "User-authored handoff note.",
        "metadata_json": {
            "privacy_policy": "public",
            "bridge_options": {"conclusions": True},
            "bridge_sections": {"conclusions": "Carry forward the reviewed result."},
        },
        "source_object_ids": [context_set.json()["id"]],
    })
    assert bridge.status_code == 201

    preview = await async_client.post(
        "/v1/workspace/projects/aura/context/preview",
        json={"selected_object_ids": [bridge.json()["id"]]},
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["privacy_requirement"] == "local_only"
    assert {item["object_id"] for item in preview_data["objects"]} == {bridge.json()["id"]}
    assert "User-authored handoff note." in preview_data["prompt_text"]
    assert "Carry forward the reviewed result." in preview_data["prompt_text"]
    assert "Private source body must not be copied into the Bridge." not in preview_data["prompt_text"]
    assert {item["object_id"] for item in preview_data["privacy_sources"]} >= {source.json()["id"]}

    calls_before = len(model_router.get_provider("mock").call_history)
    blocked = await async_client.post("/v1/chat", json={
        "session_id": "bridge-transitive-privacy-session",
        "project_name": "aura",
        "message": "Use the reviewed handoff.",
        "model_override": "openai:gpt-4o",
        "context_object_ids": [bridge.json()["id"]],
    })
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before

@pytest.mark.asyncio
async def test_context_bridge_inherits_privacy_from_provenance_ancestors(async_client, test_db_session):
    from app.db.models import WorkspaceEdgeModel
    from app.models.router import model_router

    private_source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Private evidence",
        "content": "Confidential evidence body must stay out of the Bridge.",
        "metadata_json": {"privacy_policy": "confidential"},
    })
    assert private_source.status_code == 201
    derived_source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Reviewed finding",
        "content": "A user-authored finding derived from confidential evidence.",
        "metadata_json": {"privacy_policy": "public"},
    })
    assert derived_source.status_code == 201
    test_db_session.add(WorkspaceEdgeModel(
        project_name="aura",
        source_object_id=private_source.json()["id"],
        target_object_id=derived_source.json()["id"],
        relation_type="supports",
        edge_family="provenance",
        created_by="research",
        metadata_json={},
    ))
    await test_db_session.commit()

    bridge = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "context_bridge",
        "title": "Finding handoff",
        "content": "Use the reviewed finding.",
        "metadata_json": {"privacy_policy": "public"},
        "source_object_ids": [derived_source.json()["id"]],
    })
    assert bridge.status_code == 201
    preview = await async_client.post(
        "/v1/workspace/projects/aura/context/preview",
        json={"selected_object_ids": [bridge.json()["id"]]},
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["privacy_requirement"] == "confidential"
    assert {item["object_id"] for item in preview_data["objects"]} == {bridge.json()["id"]}
    assert "Use the reviewed finding." in preview_data["prompt_text"]
    assert "Confidential evidence body must stay out of the Bridge." not in preview_data["prompt_text"]
    assert {item["object_id"] for item in preview_data["privacy_sources"]} >= {private_source.json()["id"]}

    calls_before = len(model_router.get_provider("mock").call_history)
    blocked = await async_client.post("/v1/chat", json={
        "session_id": "bridge-provenance-privacy-session",
        "project_name": "aura",
        "message": "Continue the finding.",
        "model_override": "openai:gpt-4o",
        "context_object_ids": [bridge.json()["id"]],
    })
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "PrivacyBoundaryViolation"
    assert len(model_router.get_provider("mock").call_history) == calls_before

@pytest.mark.asyncio
async def test_workspace_context_preview_is_read_only_and_honors_bridge_sections_and_source_privacy(
    async_client,
    test_db_session,
):
    from sqlalchemy import func, select
    from app.db.models import RunModel

    source = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Private source note",
        "content": "Full source detail must stay behind the bridge.",
        "metadata_json": {"privacy_policy": "local_only"},
    })
    assert source.status_code == 201
    bridge = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "context_bridge",
        "title": "Reviewed handoff",
        "content": "Carry the reviewed finding.",
        "metadata_json": {
            "bridge_options": {"conclusions": True, "observations": False, "failed": False, "artifacts": False},
            "bridge_sections": {
                "conclusions": "The regression test passes.",
                "observations": "This section is not selected.",
                "failed": "",
                "artifacts": "",
            },
        },
        "source_object_ids": [source.json()["id"]],
    })
    assert bridge.status_code == 201
    runs_before = await test_db_session.scalar(select(func.count()).select_from(RunModel))

    response = await async_client.post(
        "/v1/workspace/projects/aura/context/preview",
        json={"selected_object_ids": [bridge.json()["id"]]},
    )

    assert response.status_code == 200
    preview = response.json()
    assert preview["estimated_tokens"] > 0
    assert preview["privacy_requirement"] == "local_only"
    assert preview["objects"] == [{
        "object_id": bridge.json()["id"],
        "object_type": "context_bridge",
        "selected_by_user": True,
        "source_object_ids": [source.json()["id"]],
        "selected_sections": {"conclusions": True, "observations": False, "failed": False, "artifacts": False, "constraints": None, "decisions": None},
    }]
    assert "The regression test passes." in preview["prompt_text"]
    assert "This section is not selected." not in preview["prompt_text"]
    assert "Full source detail must stay behind the bridge." not in preview["prompt_text"]
    assert await test_db_session.scalar(select(func.count()).select_from(RunModel)) == runs_before


@pytest.mark.asyncio
async def test_context_preview_derives_all_routing_flags_from_required_capabilities(async_client):
    created = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Routing requirements",
        "content": "Preview and live routing must agree.",
        "metadata_json": {
            "required_capabilities": ["tools", "vision", "structured_output", "long_context"],
            "requires_tools": False,
            "requires_vision": False,
            "requires_structured_output": False,
            "requires_long_context": False,
        },
    })
    assert created.status_code == 201

    response = await async_client.post(
        "/v1/workspace/projects/aura/context/preview",
        json={"selected_object_ids": [created.json()["id"]]},
    )

    assert response.status_code == 200
    preview = response.json()
    assert preview["requires_tools"] is True
    assert preview["requires_vision"] is True
    assert preview["requires_structured_output"] is True
    assert preview["requires_long_context"] is True
    assert preview["missing_capabilities"] == []

@pytest.mark.asyncio
async def test_compiled_tool_capabilities_fail_closed_without_provider_and_do_not_filter_models(
    async_client,
    monkeypatch,
):
    from app.capabilities.registry import (
        CapabilityProviderHealth,
        CapabilityProviderMetadata,
        NetworkRequirement,
        PrivacyBoundary,
    )
    from app.models.router import model_router
    from app.tools.registry import tool_registry

    created = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "manual_note",
        "title": "Code graph requirement",
        "content": "Use the code graph for impact analysis.",
        "metadata_json": {"required_capabilities": ["code_graph.read"]},
    })
    assert created.status_code == 201
    object_id = created.json()["id"]
    mock_provider = model_router.get_provider("mock")
    calls_before = len(mock_provider.call_history)

    preview = await async_client.post(
        "/v1/workspace/projects/aura/context/preview",
        json={"selected_object_ids": [object_id]},
    )
    assert preview.status_code == 200
    assert preview.json()["available_capabilities"] == []
    assert preview.json()["missing_capabilities"] == ["code_graph.read"]
    assert preview.json()["requires_tools"] is True
    assert len(mock_provider.call_history) == calls_before

    missing_provider = await async_client.post("/v1/chat", json={
        "session_id": "missing-context-capability-provider",
        "project_name": "aura",
        "message": "Find the impacted callers.",
        "context_object_ids": [object_id],
    })
    assert missing_provider.status_code == 422
    assert missing_provider.json()["code"] == "ContextSelectionError"
    assert missing_provider.json()["details"]["missing_capabilities"] == ["code_graph.read"]
    assert len(mock_provider.call_history) == calls_before

    provider_id = "test.context-code-graph"
    tool_registry.register_capability_provider(
        CapabilityProviderMetadata(
            provider_id=provider_id,
            name="Test Code Graph",
            health=CapabilityProviderHealth.HEALTHY,
            capabilities=["code_graph.read"],
            privacy_boundary=PrivacyBoundary.LOCAL,
            network_requirement=NetworkRequirement.NONE,
        ),
        {"code_graph.read": ["read_workspace_file"]},
    )
    try:
        available_provider = await async_client.post("/v1/chat", json={
            "session_id": "available-capability-provider",
            "project_name": "aura",
            "message": "Find the impacted callers.",
            "context_object_ids": [object_id],
        })
    finally:
        tool_registry.unregister_capability_provider(provider_id)

    assert available_provider.status_code == 200
    run = (await async_client.get(f"/v1/runs/{available_provider.json()['run_id']}")).json()
    selected = next(event for event in run["events"] if event["event_type"] == "model_selected")
    compiled = next(event for event in run["events"] if event["event_type"] == "context_compiled")
    assert compiled["payload"]["required_tool_capabilities"] == ["code_graph.read"]
    assert compiled["payload"]["resolved_tool_names"] == ["read_workspace_file"]
    assert "code_graph.read" not in selected["payload"]["required_capabilities"]
    assert selected["payload"]["requires_tools"] is True


@pytest.mark.asyncio
async def test_confidential_context_never_exposes_cloud_capability_tools(async_client):
    from app.capabilities.registry import CapabilityProviderHealth, CapabilityProviderMetadata, NetworkRequirement, PrivacyBoundary
    from app.models.router import model_router
    from app.tools.registry import tool_registry

    note = await async_client.post('/v1/workspace/projects/aura/objects', json={
        'object_type': 'manual_note',
        'title': 'Private code context',
        'content': 'Confidential source context.',
        'metadata_json': {
            'privacy_policy': 'confidential',
            'required_capabilities': ['code_graph.read'],
        },
    })
    assert note.status_code == 201

    provider_id = 'test.cloud-code-graph'
    tool_registry.register_capability_provider(
        CapabilityProviderMetadata(
            provider_id=provider_id,
            name='Cloud Code Graph',
            health=CapabilityProviderHealth.HEALTHY,
            capabilities=['code_graph.read'],
            privacy_boundary=PrivacyBoundary.CLOUD,
            network_requirement=NetworkRequirement.INTERNET,
        ),
        {'code_graph.read': ['read_workspace_file']},
    )
    try:
        preview = await async_client.post(
            '/v1/workspace/projects/aura/context/preview',
            json={'selected_object_ids': [note.json()['id']]},
        )
        assert preview.status_code == 200
        assert preview.json()['privacy_requirement'] == 'confidential'
        assert preview.json()['available_capabilities'] == []
        assert preview.json()['missing_capabilities'] == ['code_graph.read']

        calls_before = len(model_router.get_provider('mock').call_history)
        response = await async_client.post('/v1/chat', json={
            'session_id': 'cloud-capability-session',
            'project_name': 'aura',
            'message': 'Analyze this private context.',
            'context_object_ids': [note.json()['id']],
        })
    finally:
        tool_registry.unregister_capability_provider(provider_id)

    assert response.status_code == 422
    assert response.json()['code'] == 'ContextSelectionError'
    assert response.json()['details']['missing_capabilities'] == ['code_graph.read']
    assert len(model_router.get_provider('mock').call_history) == calls_before

@pytest.mark.asyncio
async def test_saved_context_set_expands_only_its_sources_in_preview_and_chat(
    async_client, test_db_session
):
    from app.models.base import ModelRole
    from app.models.router import model_router

    async def create_note(title: str, content: str) -> str:
        response = await async_client.post("/v1/workspace/projects/aura/objects", json={
            "object_type": "manual_note",
            "title": title,
            "content": content,
        })
        assert response.status_code == 201
        return response.json()["id"]

    first_id = await create_note("Migration constraint", "Keep the schema change reversible.")
    second_id = await create_note("Deployment decision", "Deploy in two guarded stages.")
    unrelated_id = await create_note("Unselected note", "Do not include this unrelated decision.")

    saved = await async_client.post("/v1/workspace/projects/aura/objects", json={
        "object_type": "context_set",
        "title": "Migration handoff",
        "content": "",
        "metadata_json": {"source_count": 2, "source_titles": ["Migration constraint", "Deployment decision"]},
        "source_object_ids": [first_id, second_id],
    })
    assert saved.status_code == 201
    context_set_id = saved.json()["id"]
    assert saved.json()["created_by"] == "user"

    preview = await async_client.post(
        "/v1/workspace/projects/aura/context/preview",
        json={"selected_object_ids": [context_set_id]},
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    assert {item["object_id"] for item in preview_data["objects"]} == {
        first_id,
        second_id,
        context_set_id,
    }
    selected = {item["object_id"]: item["selected_by_user"] for item in preview_data["objects"]}
    assert selected == {first_id: False, second_id: False, context_set_id: True}
    context_set_manifest = next(item for item in preview_data["objects"] if item["object_id"] == context_set_id)
    assert context_set_manifest["source_object_ids"] == sorted([first_id, second_id])
    assert "Keep the schema change reversible." in preview_data["prompt_text"]
    assert "Deploy in two guarded stages." in preview_data["prompt_text"]
    assert "Do not include this unrelated decision." not in preview_data["prompt_text"]

    response = await async_client.post("/v1/chat", json={
        "session_id": "saved-context-set-session",
        "project_name": "aura",
        "message": "Continue the migration plan from this saved selection.",
        "context_object_ids": [context_set_id],
    })
    assert response.status_code == 200
    request = model_router.get_provider("mock").call_history[-1]
    system_message = next(message for message in request.messages if message.role == ModelRole.SYSTEM)
    assert "Keep the schema change reversible." in system_message.content
    assert "Deploy in two guarded stages." in system_message.content
    assert "Do not include this unrelated decision." not in system_message.content

    run = (await async_client.get(f"/v1/runs/{response.json()['run_id']}")).json()
    compiled_event = next(event for event in run["events"] if event["event_type"] == "context_compiled")
    assert {item["object_id"] for item in compiled_event["payload"]["objects"]} == {
        first_id,
        second_id,
        context_set_id,
    }

@pytest.mark.asyncio
async def test_workspace_execution_graph_projects_sanitized_routing_provenance(async_client, test_db_session):
    session = SessionModel(
        id="routing-provenance-session",
        title="Routing provenance",
        metadata_json={},
        project_name="aura",
    )
    run = RunModel(
        id="routing-provenance-run",
        session_id=session.id,
        status="failed",
        user_message="private user prompt",
    )
    occurred = datetime(2026, 10, 2, tzinfo=timezone.utc)
    events = [
        RunEventModel(
            id="routing-model-event",
            run_id=run.id,
            event_type="model_selected",
            created_at=occurred,
            payload={
                "agent_role": "root",
                "task_type": "research",
                "provider": "ollama",
                "model": "local-model",
                "profile_id": "profile-safe",
                "profile_version": 4,
                "winning_scope": "project",
                "privacy": "local_only",
                "fallback_policy": "none",
                "selection_reason": "explicit_profile_route",
                "prompt": "private model prompt",
            },
        ),
        RunEventModel(
            id="routing-reasoning-event",
            run_id=run.id,
            event_type="reasoning_effort_selected",
            created_at=occurred + timedelta(seconds=1),
            payload={
                "policy_mode": "adaptive",
                "configured_bounds": {"min": "low", "max": "high", "secret": "omit"},
                "selected_effort": "medium",
                "private_reasoning": "never expose",
            },
        ),
        RunEventModel(
            id="routing-fallback-event",
            run_id=run.id,
            event_type="fallback_considered",
            created_at=occurred + timedelta(seconds=2),
            payload={
                "fallback_policy": "local_only",
                "primary_provider": "cloud",
                "selected_provider": "ollama",
                "candidate_model": "local-model",
                "private_reason": "omit this",
            },
        ),
        RunEventModel(
            id="routing-blocked-event",
            run_id=run.id,
            event_type="fallback_blocked",
            created_at=occurred + timedelta(seconds=3),
            payload={
                "policy": "ask_before_cloud",
                "error_type": "RoutingConfirmationRequired",
                "privacy_boundary": "confidential",
                "proposed_provider": "cloud-provider",
                "proposed_model": "exact-model",
                "private_reason": "omit this too",
            },
        ),
    ]
    test_db_session.add_all([session, run, *events])
    await test_db_session.commit()

    response = await async_client.get("/v1/workspace/projects/aura/graph")
    assert response.status_code == 200
    trace = next(item for item in response.json()["execution_traces"] if item["run_id"] == run.id)
    model, reasoning, fallback, blocked = trace["events"]
    assert (
        model["task_type"], model["profile_id"], model["profile_version"],
        model["winning_scope"], model["privacy"], model["fallback_policy"],
    ) == ("research", "profile-safe", 4, "project", "local_only", "none")
    assert (reasoning["reasoning_policy"], reasoning["reasoning_bounds"], reasoning["selected_effort"]) == (
        "adaptive", {"min": "low", "max": "high"}, "medium",
    )
    assert (
        fallback["fallback_policy"], fallback["primary_provider"], fallback["selected_provider"],
        fallback["candidate_model"],
    ) == ("local_only", "cloud", "ollama", "local-model")
    assert (
        blocked["fallback_policy"], blocked["privacy_boundary"], blocked["error_type"],
        blocked["proposed_provider"], blocked["proposed_model"],
    ) == ("ask_before_cloud", "confidential", "RoutingConfirmationRequired", "cloud-provider", "exact-model")
    for private_value in ("private user prompt", "private model prompt", "never expose", "omit this"):
        assert private_value not in response.text
    assert "secret" not in str(reasoning["reasoning_bounds"])

@pytest.mark.asyncio
async def test_workspace_graph_projects_automation_origin_without_instruction(async_client, test_db_session):
    session = SessionModel(
        id="automation-provenance-session",
        title="Automation review",
        metadata_json={},
        project_name="Atlas",
    )
    run = RunModel(
        id="automation-provenance-run",
        session_id=session.id,
        status="completed",
        user_message="private automation instruction",
    )
    event = RunEventModel(
        id="automation-triggered-event",
        run_id=run.id,
        event_type="automation_triggered",
        created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
        payload={
            "trigger_event_id": "event-safe-id",
            "automation_id": "automation-safe-id",
            "automation_name": "Atlas review",
            "message": "private automation instruction",
        },
    )
    test_db_session.add_all([session, run, event])
    await test_db_session.commit()

    response = await async_client.get("/v1/workspace/projects/Atlas/graph")
    assert response.status_code == 200
    trace = next(item for item in response.json()["execution_traces"] if item["run_id"] == run.id)
    assert len(trace["events"]) == 1
    projected = trace["events"][0]
    assert (projected["event_type"], projected["trigger_event_id"], projected["automation_id"], projected["automation_name"]) == (
        "automation_triggered", "event-safe-id", "automation-safe-id", "Atlas review",
    )
    assert "message" not in projected
    assert "private automation instruction" not in response.text


@pytest.mark.asyncio
async def test_context_compilation_trace_exposes_only_safe_manifest_provenance(async_client, test_db_session):
    session = SessionModel(id="context-manifest-session", title="Context manifest", metadata_json={}, project_name="aura")
    run = RunModel(id="context-manifest-run", session_id=session.id, status="completed", user_message="private user message")
    occurred = datetime(2026, 10, 2, tzinfo=timezone.utc)
    event = RunEventModel(
        id="context-manifest-event",
        run_id=run.id,
        event_type="context_compiled",
        created_at=occurred,
        payload={
            "objects": [
                {
                    "object_id": "selected-note",
                    "object_type": "manual_note",
                    "selected_by_user": True,
                    "source_object_ids": [],
                    "selected_sections": {"conclusions": True, "untrusted": "private section body"},
                    "content": "private note body",
                },
                {
                    "object_id": "linked-note",
                    "object_type": "manual_note",
                    "selected_by_user": False,
                    "source_object_ids": ["selected-note", "selected-note"],
                    "selected_sections": {"observations": False},
                },
                {"object_id": "invalid-object", "object_type": 7, "selected_by_user": True},
            ],
            "estimated_tokens": 42,
            "privacy_requirement": "internal",
            "prompt_text": "private compiled prompt",
            "privacy_sources": [{"private": "source detail"}],
            "required_tool_capabilities": ["private.tool.argument"],
        },
    )
    test_db_session.add_all([session, run, event])
    await test_db_session.commit()

    response = await async_client.get("/v1/workspace/projects/aura/graph")
    assert response.status_code == 200
    trace = next(item for item in response.json()["execution_traces"] if item["run_id"] == run.id)
    [compiled] = trace["events"]
    assert compiled["event_type"] == "context_compiled"
    assert compiled["context_objects"] == [
        {
            "object_id": "selected-note",
            "object_type": "manual_note",
            "selected_by_user": True,
            "source_object_ids": [],
            "selected_sections": {"conclusions": True},
        },
        {
            "object_id": "linked-note",
            "object_type": "manual_note",
            "selected_by_user": False,
            "source_object_ids": ["selected-note"],
            "selected_sections": {"observations": False},
        },
    ]
    assert compiled["context_estimated_tokens"] == 42
    assert compiled["context_privacy_requirement"] == "internal"
    serialized_event = str(trace["events"])
    for private_value in ("private user message", "private note body", "private compiled prompt", "source detail", "private.tool.argument"):
        assert private_value not in serialized_event


@pytest.mark.asyncio
async def test_workspace_graph_marks_execution_history_truncated_at_event_limit(async_client, test_db_session):
    from app.api.routes.workspace import MAX_EXECUTION_GRAPH_EVENTS
    from app.db.models import RunEventModel

    session = SessionModel(id="bounded-trace-session", title="Bounded trace", metadata_json={}, project_name="aura")
    run = RunModel(id="bounded-trace-run", session_id=session.id, status="completed", user_message="Question")
    test_db_session.add_all([session, run])
    await test_db_session.flush()
    test_db_session.add_all([
        RunEventModel(run_id=run.id, event_type="run_completed", payload={})
        for _ in range(MAX_EXECUTION_GRAPH_EVENTS + 1)
    ])
    await test_db_session.commit()

    response = await async_client.get("/v1/workspace/projects/aura/graph")

    assert response.status_code == 200
    graph = response.json()
    assert graph["execution_history_truncated"] is True
    [trace] = graph["execution_traces"]
    assert len(trace["events"]) == MAX_EXECUTION_GRAPH_EVENTS


@pytest.mark.asyncio
async def test_workspace_execution_history_cursor_pages_runs_without_overlap(async_client, test_db_session):
    from datetime import datetime, timezone
    from app.db.models import RunEventModel

    session = SessionModel(id="paged-trace-session", title="Paged trace", metadata_json={}, project_name="aura")
    run_ids = ["paged-trace-1", "paged-trace-2", "paged-trace-3"]
    created_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    runs = [
        RunModel(
            id=run_id,
            session_id=session.id,
            status="completed",
            user_message=run_id,
            created_at=created_at,
        )
        for run_id in run_ids
    ]
    test_db_session.add_all([session, *runs])
    await test_db_session.flush()
    test_db_session.add_all([
        RunEventModel(run_id=run.id, event_type="run_completed", payload={})
        for run in runs
    ])
    await test_db_session.commit()

    first_page = await async_client.get(
        "/v1/workspace/projects/aura/execution",
        params={"execution_page_size": 2},
    )
    assert first_page.status_code == 200
    first = first_page.json()
    assert [trace["run_id"] for trace in first["execution_traces"]] == sorted(run_ids, reverse=True)[:2][::-1]
    assert first["execution_next_cursor"]
    assert first["execution_history_truncated"] is False

    second_page = await async_client.get(
        "/v1/workspace/projects/aura/execution",
        params={"execution_page_size": 2, "execution_cursor": first["execution_next_cursor"]},
    )
    assert second_page.status_code == 200
    second = second_page.json()
    assert [trace["run_id"] for trace in second["execution_traces"]] == [sorted(run_ids)[0]]
    assert second["execution_next_cursor"] is None
    assert second["execution_history_truncated"] is False


@pytest.mark.asyncio
async def test_workspace_execution_history_scales_beyond_sqlite_session_bind_limit(async_client, test_db_session):
    from app.db.models import RunEventModel

    project_name = "many-session-project"
    sessions = [
        SessionModel(id=f"many-session-{index:04d}", title="Session", metadata_json={}, project_name=project_name)
        for index in range(1_100)
    ]
    run = RunModel(
        id="many-session-run",
        session_id=sessions[-1].id,
        status="completed",
        user_message="Query the latest run",
    )
    test_db_session.add_all([*sessions, run])
    await test_db_session.flush()
    test_db_session.add(RunEventModel(run_id=run.id, event_type="run_completed", payload={}))
    await test_db_session.commit()

    response = await async_client.get(f"/v1/workspace/projects/{project_name}/execution")

    assert response.status_code == 200
    assert [trace["run_id"] for trace in response.json()["execution_traces"]] == [run.id]


@pytest.mark.asyncio
async def test_workspace_execution_history_rejects_invalid_cursor(async_client):
    response = await async_client.get(
        "/v1/workspace/projects/aura/graph",
        params={"execution_cursor": "not-a-valid-cursor"},
    )
    assert response.status_code == 422
