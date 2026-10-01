import pytest


@pytest.mark.asyncio
async def test_study_session_lifecycle_persists_in_the_shared_workspace_graph(async_client):
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
async def test_study_session_rejects_blank_track_and_unknown_completion(async_client):
    blank = await async_client.post("/v1/study/sessions", json={
        "track_id": " ",
        "track_title": "German A1",
    })
    assert blank.status_code == 422

    missing = await async_client.post("/v1/study/sessions/not-a-session/complete")
    assert missing.status_code == 404
