"""Durable Study focus session API invariants."""

import pytest

from app.db.models import StudySessionModel


@pytest.mark.asyncio
async def test_study_session_lifecycle_is_durable_idempotent_and_single_active(async_client, test_db_session):
    started = await async_client.post("/v1/study/sessions", json={"id": "focus-session-1", "track_id": "german"})
    assert started.status_code == 201
    assert started.json()["status"] == "active"
    assert started.json()["track_id"] == "german"

    # A retried start with the same client identity returns the existing row.
    retried = await async_client.post("/v1/study/sessions", json={"id": "focus-session-1", "track_id": "german"})
    assert retried.status_code == 201
    assert retried.json()["id"] == started.json()["id"]
    assert await test_db_session.get(StudySessionModel, "focus-session-1") is not None

    wrong_track = await async_client.post("/v1/study/sessions", json={"id": "focus-session-1", "track_id": "toeic"})
    assert wrong_track.status_code == 409
    blocked = await async_client.post("/v1/study/sessions", json={"id": "focus-session-2", "track_id": "toeic"})
    assert blocked.status_code == 409

    completed = await async_client.post("/v1/study/sessions/focus-session-1/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None
    assert completed.json()["duration_seconds"] >= 0
    assert (await async_client.post("/v1/study/sessions/focus-session-1/complete")).json() == completed.json()

    next_session = await async_client.post("/v1/study/sessions", json={"id": "focus-session-2", "track_id": "toeic"})
    assert next_session.status_code == 201
    listed = await async_client.get("/v1/study/sessions")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} == {"focus-session-1", "focus-session-2"}


@pytest.mark.asyncio
async def test_study_session_can_only_be_completed_when_it_exists(async_client):
    assert (await async_client.post("/v1/study/sessions/missing/complete")).status_code == 404
