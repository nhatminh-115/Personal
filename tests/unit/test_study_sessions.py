"""Study sessions retain identity links to shared personal workspace objects."""

import asyncio

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_study_session_lifecycle_persists_in_the_shared_workspace_graph(async_client: AsyncClient):
    started = await async_client.post("/v1/study/sessions", json={
        "track_id": "german",
        "track_title": "German A1",
    })
    assert started.status_code == 201
    session = started.json()
    assert session["track_id"] == "german"
    assert session["track_title"] == "German A1"
    assert session["status"] == "in_progress"
    assert session["reflection"] == ""
    assert session["completed_at"] is None

    persisted = await async_client.get("/v1/study/sessions")
    assert [item["id"] for item in persisted.json()] == [session["id"]]

    completed = await async_client.post(f"/v1/study/sessions/{session['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None

    repeated = await async_client.post(f"/v1/study/sessions/{session['id']}/complete")
    assert repeated.json() == completed.json()


@pytest.mark.asyncio
async def test_study_session_rejects_blank_track_and_unknown_completion(async_client: AsyncClient):
    blank = await async_client.post("/v1/study/sessions", json={
        "track_id": " ",
        "track_title": "German A1",
    })
    assert blank.status_code == 422

    missing = await async_client.post("/v1/study/sessions/not-a-session/complete")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_study_session_persists_and_returns_library_material_link(async_client: AsyncClient):
    library = await async_client.post(
        "/v1/workspace/library",
        json={
            "name": "Language notes.pdf",
            "kind": "PDF",
            "collection": "Study",
            "detail": "Vocabulary notes",
            "tags": ["language"],
            "project_names": ["aura"],
        },
    )
    assert library.status_code == 201
    material_id = library.json()["id"]

    started = await async_client.post(
        "/v1/study/sessions",
        json={"track_id": "stale-id", "track_title": "Stale title", "material_id": material_id},
    )
    assert started.status_code == 201
    assert started.json()["material_id"] == material_id
    assert started.json()["track_id"] == material_id
    assert started.json()["track_title"] == "Language notes.pdf"

    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    study_object = next(item for item in graph["objects"] if item["id"] == started.json()["id"])
    assert study_object["object_type"] == "study_session"
    [material_edge] = [
        edge for edge in graph["edges"]
        if edge["source_object_id"] == material_id
        and edge["target_object_id"] == study_object["id"]
    ]
    assert material_edge["relation_type"] == "studied_from"
    assert material_edge["edge_family"] == "provenance"

    listed = await async_client.get("/v1/study/sessions")
    assert listed.status_code == 200
    assert listed.json()[0]["material_id"] == material_id

    completed = await async_client.post(f"/v1/study/sessions/{started.json()['id']}/complete")
    assert completed.status_code == 200
    assert completed.json()["material_id"] == material_id
    assert completed.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_study_session_rejects_non_study_library_material(async_client: AsyncClient):
    library = await async_client.post(
        "/v1/workspace/library",
        json={"name": "General reference.pdf", "kind": "PDF", "collection": "Books"},
    )
    assert library.status_code == 201

    response = await async_client.post(
        "/v1/study/sessions",
        json={
            "track_id": library.json()["id"],
            "track_title": "General reference.pdf",
            "material_id": library.json()["id"],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Study source not found or not eligible."


@pytest.mark.asyncio
async def test_study_session_can_link_only_verified_project_research_claims(async_client: AsyncClient, test_db_session):
    from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel

    verified = WorkspaceObjectModel(
        id="10000000-0000-4000-8000-000000000001",
        project_name="research-project",
        object_type="research_claim",
        created_by="research",
        title="A verified finding",
        content="Supported by cited evidence.",
        metadata_json={"verification_status": "verified", "privacy_policy": "public"},
    )
    pending = WorkspaceObjectModel(
        id="10000000-0000-4000-8000-000000000002",
        project_name="research-project",
        object_type="research_claim",
        created_by="research",
        title="An unverified finding",
        content="This is still uncertain.",
        metadata_json={"verification_status": "unsupported"},
    )
    evidence = WorkspaceObjectModel(
        id="10000000-0000-4000-8000-000000000003",
        project_name="research-project",
        object_type="research_evidence",
        created_by="research",
        title="Internal evidence",
        content="Sensitive source excerpt.",
        metadata_json={"privacy_policy": "local_only"},
    )
    test_db_session.add_all([verified, pending, evidence])
    test_db_session.add(WorkspaceEdgeModel(
        id="20000000-0000-4000-8000-000000000001",
        project_name="research-project",
        source_object_id=evidence.id,
        target_object_id=verified.id,
        relation_type="supports_claim",
        edge_family="provenance",
        created_by="research",
    ))
    await test_db_session.commit()

    started = await async_client.post("/v1/study/sessions", json={
        "track_id": verified.id,
        "track_title": "Stale client title",
        "material_id": verified.id,
        "material_project_name": "research-project",
    })
    assert started.status_code == 201
    assert started.json()["material_id"] == verified.id
    assert started.json()["material_project_name"] == "research-project"
    assert started.json()["track_title"] == verified.title

    saved_reflection = await async_client.put(
        f"/v1/study/sessions/{started.json()['id']}/reflection",
        json={"reflection": "Separate the verified claim from its supporting evidence."},
    )
    assert saved_reflection.status_code == 200
    assert saved_reflection.json()["reflection"] == "Separate the verified claim from its supporting evidence."

    graph_response = await async_client.get("/v1/workspace/projects/research-project/graph")
    assert graph_response.status_code == 200
    graph = graph_response.json()
    session_object = next(item for item in graph["objects"] if item["id"] == started.json()["id"])
    assert session_object["object_type"] == "study_session"
    provenance = [
        edge for edge in graph["edges"]
        if edge["source_object_id"] == verified.id
        and edge["target_object_id"] == started.json()["id"]
    ]
    assert len(provenance) == 1
    assert provenance[0]["relation_type"] == "studied_in"
    assert provenance[0]["edge_family"] == "provenance"

    from app.memory.context_compiler import WorkspaceContextCompiler
    compiled = await WorkspaceContextCompiler(test_db_session).compile(
        "research-project", [started.json()["id"]]
    )
    assert [item.object_id for item in compiled.objects] == [started.json()["id"]]
    assert "A verified finding" in compiled.prompt_text
    assert "Separate the verified claim from its supporting evidence." in compiled.prompt_text
    assert "Supported by cited evidence." not in compiled.prompt_text
    assert compiled.privacy_requirement == "local_only"
    assert compiled.privacy_sources == [
        {"object_id": verified.id, "privacy_policy": "public"},
        {"object_id": evidence.id, "privacy_policy": "local_only"},
    ]
    assert compiled.objects[0].source_object_ids == [verified.id]
    assert evidence.id not in compiled.prompt_text
    assert evidence.content not in compiled.prompt_text

    refused = await async_client.post("/v1/study/sessions", json={
        "track_id": pending.id,
        "track_title": pending.title,
        "material_id": pending.id,
        "material_project_name": "research-project",
    })
    assert refused.status_code == 404


@pytest.mark.asyncio
async def test_study_workspace_allows_only_one_active_session(async_client: AsyncClient):
    first = await async_client.post("/v1/study/sessions", json={
        "track_id": "first-track",
        "track_title": "First track",
    })
    assert first.status_code == 201

    blocked = await async_client.post("/v1/study/sessions", json={
        "track_id": "second-track",
        "track_title": "Second track",
    })
    assert blocked.status_code == 409
    assert "already active" in blocked.json()["detail"]

    completed = await async_client.post(f"/v1/study/sessions/{first.json()['id']}/complete")
    assert completed.status_code == 200

    second = await async_client.post("/v1/study/sessions", json={
        "track_id": "second-track",
        "track_title": "Second track",
    })
    assert second.status_code == 201
    assert second.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_concurrent_study_starts_create_at_most_one_active_session(
    async_client: AsyncClient,
    test_db_session,
):
    if test_db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("The production concurrency guarantee uses PostgreSQL advisory locks.")

    responses = await asyncio.gather(
        async_client.post("/v1/study/sessions", json={
            "track_id": "concurrent-track-a",
            "track_title": "Concurrent track A",
        }),
        async_client.post("/v1/study/sessions", json={
            "track_id": "concurrent-track-b",
            "track_title": "Concurrent track B",
        }),
    )

    assert sorted(response.status_code for response in responses) == [201, 409]
    sessions = (await async_client.get("/v1/study/sessions")).json()
    assert len([session for session in sessions if session["status"] == "in_progress"]) == 1
