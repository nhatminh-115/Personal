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
