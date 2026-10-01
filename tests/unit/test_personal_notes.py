"""Durable personal Notes API invariants."""

import pytest
from sqlalchemy import select

from app.db.models import PersonalNoteModel


@pytest.mark.asyncio
async def test_personal_notes_crud_preserves_user_content_and_workspace_links(async_client, test_db_session):
    created = await async_client.post("/v1/notes", json={
        "id": "note-stable-1",
        "title": "  Research constraints  ",
        "body": "Keep the user's exact sentence.\nDo not rewrite it.",
        "tags": [" research ", "research", "stateful"],
        "project_ids": ["stateful", "stateful", "aura"],
        "project_names": ["Stateful Architecture", "AURA", "AURA"],
        "pinned": True,
    })
    assert created.status_code == 201
    created_note = created.json()
    assert created_note["title"] == "  Research constraints  "
    assert created_note["body"] == "Keep the user's exact sentence.\nDo not rewrite it."
    assert created_note["tags"] == ["research", "stateful"]
    assert created_note["project_ids"] == ["stateful", "aura"]
    assert created_note["project_names"] == ["Stateful Architecture", "AURA"]
    assert created_note["pinned"] is True

    listed = await async_client.get("/v1/notes")
    assert listed.status_code == 200
    assert listed.json() == [created_note]

    updated = await async_client.put("/v1/notes/note-stable-1", json={
        "title": "Research constraints v2",
        "body": "Edited deliberately by the user.",
        "tags": ["updated"],
        "project_ids": ["aura"],
        "project_names": ["AURA"],
        "pinned": False,
    })
    assert updated.status_code == 200
    assert updated.json()["created_at"] == created_note["created_at"]
    assert updated.json()["updated_at"] >= created_note["updated_at"]
    assert updated.json()["body"] == "Edited deliberately by the user."

    row = await test_db_session.get(PersonalNoteModel, "note-stable-1")
    assert row is not None
    assert row.body == "Edited deliberately by the user."

    deleted = await async_client.delete("/v1/notes/note-stable-1")
    assert deleted.status_code == 204
    assert await test_db_session.get(PersonalNoteModel, "note-stable-1") is None
    assert (await async_client.delete("/v1/notes/note-stable-1")).status_code == 404


@pytest.mark.asyncio
async def test_personal_note_create_is_retry_safe_for_client_generated_ids(async_client, test_db_session):
    payload = {
        "id": "note-retry-1",
        "title": "Updated after retry",
        "body": "Latest client state wins for the same note identity.",
        "tags": [],
        "project_ids": [],
        "project_names": [],
        "pinned": False,
    }
    first = await async_client.post("/v1/notes", json={**payload, "title": "Original"})
    retried = await async_client.post("/v1/notes", json=payload)
    assert first.status_code == retried.status_code == 201
    rows = list((await test_db_session.execute(select(PersonalNoteModel))).scalars())
    assert len(rows) == 1
    assert rows[0].title == "Updated after retry"
