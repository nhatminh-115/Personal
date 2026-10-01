"""Study sessions retain identity links to shared personal workspace objects."""

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
    assert response.json()["detail"] == "Study material not found in the personal Library."
