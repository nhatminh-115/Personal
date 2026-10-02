from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_user_project_directory_persists_projects_and_rejects_casefold_duplicates(async_client):
    project_id = str(uuid4())
    created = await async_client.post("/v1/workspace/projects", json={
        "id": project_id,
        "name": "Field Notes",
        "subtitle": "A durable project context",
    })
    assert created.status_code == 201
    assert created.json()["id"] == project_id
    assert created.json()["name"] == "Field Notes"

    listed = await async_client.get("/v1/workspace/projects")
    assert [item["id"] for item in listed.json()] == [project_id]

    duplicate = await async_client.post("/v1/workspace/projects", json={"name": "field notes"})
    assert duplicate.status_code == 409

    blank = await async_client.post("/v1/workspace/projects", json={"name": "   "})
    assert blank.status_code == 422


@pytest.mark.asyncio
async def test_workspace_projects_page_with_a_stable_next_cursor(async_client):
    for name in ("Project A", "Project B", "Project C"):
        created = await async_client.post("/v1/workspace/projects", json={"name": name})
        assert created.status_code == 201

    full = (await async_client.get("/v1/workspace/projects")).json()
    first = await async_client.get("/v1/workspace/projects", params={"page_size": 2})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()] == [item["id"] for item in full[:2]]
    cursor = first.headers.get("X-Next-Cursor")
    assert cursor

    second = await async_client.get("/v1/workspace/projects", params={"page_size": 2, "cursor": cursor})
    assert [item["id"] for item in second.json()] == [item["id"] for item in full[2:]]
    assert second.headers.get("X-Next-Cursor") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path,items", [
    ("/v1/workspace/notes", [{"title": f"Note {index}", "body": f"Body {index}"} for index in range(3)]),
    ("/v1/workspace/library", [{"name": f"File {index}", "kind": "PDF", "collection": "Books"} for index in range(3)]),
])
async def test_personal_collections_page_without_changing_array_response_shape(async_client, path, items):
    for item in items:
        created = await async_client.post(path, json=item)
        assert created.status_code == 201

    full = (await async_client.get(path)).json()
    first = await async_client.get(path, params={"page_size": 2})
    assert first.status_code == 200
    assert isinstance(first.json(), list)
    assert [item["id"] for item in first.json()] == [item["id"] for item in full[:2]]
    cursor = first.headers.get("X-Next-Cursor")
    assert cursor

    second = await async_client.get(path, params={"page_size": 2, "cursor": cursor})
    assert [item["id"] for item in second.json()] == [item["id"] for item in full[2:]]
    assert second.headers.get("X-Next-Cursor") is None


@pytest.mark.asyncio
async def test_workspace_collection_rejects_invalid_cursor(async_client):
    response = await async_client.get(
        "/v1/workspace/notes",
        params={"cursor": "not-a-cursor"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid pagination cursor."
    assert "x-next-cursor" in response.headers.get("access-control-expose-headers", "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/v1/workspace/projects",
    "/v1/workspace/notes",
    "/v1/workspace/library",
])
async def test_workspace_collection_rejects_page_size_over_hard_limit(async_client, path):
    response = await async_client.get(path, params={"page_size": 501})
    assert response.status_code == 422
