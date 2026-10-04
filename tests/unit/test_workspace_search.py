"""Search returns safe snippets from persisted workspace objects."""

import pytest


@pytest.mark.asyncio
async def test_workspace_search_returns_ranked_matches_without_metadata(async_client):
    response = await async_client.post(
        "/v1/workspace/projects/aura/objects",
        json={
            "object_type": "manual_note",
            "title": "Searchable finding",
            "content": "The exact phrase appears in this evidence summary.",
            "metadata_json": {"secret": "must not be returned"},
        },
    )
    assert response.status_code == 201

    result = await async_client.get("/v1/workspace/search", params={"query": "exact phrase"})
    assert result.status_code == 200
    assert len(result.json()) == 1
    assert result.json()[0]["title"] == "Searchable finding"
    assert "exact phrase" in result.json()[0]["excerpt"]
    assert "metadata_json" not in result.json()[0]
    assert "secret" not in result.text


@pytest.mark.asyncio
async def test_project_search_includes_linked_personal_objects_only(async_client):
    project = await async_client.post("/v1/workspace/projects", json={"name": "Search Project"})
    assert project.status_code == 201
    note = await async_client.post(
        "/v1/workspace/notes",
        json={"title": "Shared research note", "body": "uniqueprojectphrase", "tags": [], "project_names": ["Search Project"], "pinned": False},
    )
    unrelated_note = await async_client.post(
        "/v1/workspace/notes",
        json={"title": "Private research note", "body": "uniqueprojectphrase", "tags": [], "project_names": [], "pinned": False},
    )
    project_object = await async_client.post(
        "/v1/workspace/projects/Search%20Project/objects",
            json={"object_type": "manual_note", "title": "Project turn", "content": "uniqueprojectphrase"},
    )
    assert note.status_code == unrelated_note.status_code == project_object.status_code == 201

    result = await async_client.get(
        "/v1/workspace/search", params={"query": "uniqueprojectphrase", "project_name": "Search Project"}
    )
    ids = {item["object_id"] for item in result.json()}
    assert note.json()["id"] in ids
    assert project_object.json()["id"] in ids
    assert unrelated_note.json()["id"] not in ids


@pytest.mark.asyncio
async def test_workspace_search_treats_wildcards_literally_and_caps_results(async_client):
    for index in range(3):
        response = await async_client.post(
            "/v1/workspace/projects/aura/objects",
            json={"object_type": "manual_note", "title": f"Literal % item {index}", "content": "wildcard control"},
        )
        assert response.status_code == 201

    literal = await async_client.get("/v1/workspace/search", params={"query": "%", "limit": 1})
    assert literal.status_code == 200
    assert len(literal.json()) == 1
    wildcard = await async_client.get("/v1/workspace/search", params={"query": "_"})
    assert wildcard.status_code == 200
    assert wildcard.json() == []
    blank = await async_client.get("/v1/workspace/search", params={"query": "   "})
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_workspace_search_paginates_ranked_results_without_duplicates(async_client):
    records = [
        ("cursor needle", "exact title"),
        ("Cursor needle alpha", "prefix title"),
        ("Cursor needle beta", "prefix title"),
        ("Unrelated title", "cursor needle in the body"),
    ]
    ids = []
    for title, content in records:
        response = await async_client.post("/v1/workspace/projects/aura/objects", json={
            "object_type": "manual_note", "title": title, "content": content,
        })
        assert response.status_code == 201
        ids.append(response.json()["id"])

    first = await async_client.get("/v1/workspace/search", params={"query": "cursor needle", "limit": 2})
    first_ids = [item["object_id"] for item in first.json()]
    assert first_ids[0] == ids[0]
    assert first_ids[1] in ids[1:3]
    cursor = first.headers.get("X-Next-Cursor")
    assert cursor

    second = await async_client.get("/v1/workspace/search", params={
        "query": "cursor needle", "limit": 2, "cursor": cursor,
    })
    second_ids = [item["object_id"] for item in second.json()]
    assert set(second_ids) == (set(ids[1:3]) - {first_ids[1]}) | {ids[3]}
    assert second_ids[-1] == ids[3]
    assert second.headers.get("X-Next-Cursor") is None
    assert not ({item["object_id"] for item in first.json()} & {item["object_id"] for item in second.json()})

    invalid_cursor = await async_client.get("/v1/workspace/search", params={"query": "cursor needle", "cursor": "invalid"})
    assert invalid_cursor.status_code == 422


@pytest.mark.asyncio
async def test_workspace_search_indexes_library_reference_metadata_without_reading_files(async_client):
    created = await async_client.post(
        "/v1/workspace/library",
        json={
            "name": "architecture.pdf", "kind": "PDF", "collection": "Books",
            "detail": "Graph systems reference", "tags": ["workspace-index"],
        },
    )
    assert created.status_code == 201

    result = await async_client.get("/v1/workspace/search", params={"query": "workspace-index"})
    assert result.status_code == 200
    assert len(result.json()) == 1
    assert result.json()[0]["title"] == "architecture.pdf"
    assert result.json()[0]["excerpt"] == "workspace-index"
    assert "storage_location" not in result.text




@pytest.mark.asyncio
async def test_workspace_search_exposes_only_research_claim_verification_status(async_client, test_db_session):
    from app.db.models import WorkspaceObjectModel

    claim = WorkspaceObjectModel(
        id="20000000-0000-4000-8000-000000000001",
        project_name="Research Project",
        object_type="research_claim",
        created_by="research",
        title="Verified graph finding",
        content="verified-claim-search-token",
        metadata_json={"verification_status": "verified", "private_notes": "never expose"},
    )
    note = WorkspaceObjectModel(
        id="20000000-0000-4000-8000-000000000002",
        project_name="Research Project",
        object_type="manual_note",
        created_by="user",
        title="Ordinary note",
        content="ordinary-note-search-token",
        metadata_json={"verification_status": "verified", "private_notes": "never expose"},
    )
    test_db_session.add_all([claim, note])
    await test_db_session.commit()

    verified = await async_client.get("/v1/workspace/search", params={"query": "verified-claim-search-token"})
    assert verified.status_code == 200
    assert verified.json()[0]["verification_status"] == "verified"
    assert "never expose" not in verified.text

    ordinary = await async_client.get("/v1/workspace/search", params={"query": "ordinary-note-search-token"})
    assert ordinary.status_code == 200
    assert ordinary.json()[0]["verification_status"] is None


@pytest.mark.asyncio
async def test_workspace_search_links_learning_cards_to_their_study_session(async_client):
    session = await async_client.post("/v1/study/sessions", json={
        "track_id": "search-study-source",
        "track_title": "Searchable Study session",
    })
    assert session.status_code == 201

    card = await async_client.post(
        f"/v1/study/sessions/{session.json()['id']}/cards",
        json={"question": "What is searchable?", "answer": "A learning card in the workspace graph."},
    )
    assert card.status_code == 201

    result = await async_client.get(
        "/v1/workspace/search",
        params={"query": "What is searchable?"},
    )
    assert result.status_code == 200
    [match] = result.json()
    assert match["object_id"] == card.json()["id"]
    assert match["object_type"] == "study_card"
    assert match["related_object_id"] == session.json()["id"]
    assert "metadata_json" not in match
