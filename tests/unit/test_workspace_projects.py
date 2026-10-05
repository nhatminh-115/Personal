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
async def test_workspace_project_archive_hides_without_deleting_and_can_be_restored(async_client):
    created = await async_client.post("/v1/workspace/projects", json={
        "name": "Archive me",
        "subtitle": "Keep all project history",
    })
    assert created.status_code == 201
    project = created.json()
    assert project["archived_at"] is None

    archived = await async_client.post(f"/v1/workspace/projects/{project['id']}/archive", json={"expected_revision": project["revision"]})
    assert archived.status_code == 200
    assert archived.json()["revision"] == project["revision"] + 1
    archived_at = archived.json()["archived_at"]
    assert archived_at is not None
    assert archived.json()["name"] == "Archive me"

    duplicate_name = await async_client.post("/v1/workspace/projects", json={"name": "Archive me"})
    assert duplicate_name.status_code == 409

    active_list = await async_client.get("/v1/workspace/projects")
    assert active_list.status_code == 200
    assert project["id"] not in {item["id"] for item in active_list.json()}

    all_projects = await async_client.get("/v1/workspace/projects", params={"include_archived": True})
    assert all_projects.status_code == 200
    archived_record = next(item for item in all_projects.json() if item["id"] == project["id"])
    assert archived_record["archived_at"] == archived_at

    repeated_archive = await async_client.post(
        f"/v1/workspace/projects/{project['id']}/archive", json={"expected_revision": archived.json()["revision"]}
    )
    assert repeated_archive.json()["archived_at"] == archived_at
    assert repeated_archive.json()["revision"] == archived.json()["revision"]

    restored = await async_client.post(
        f"/v1/workspace/projects/{project['id']}/restore", json={"expected_revision": archived.json()["revision"]}
    )
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert restored.json()["revision"] == archived.json()["revision"] + 1
    visible_again = await async_client.get("/v1/workspace/projects")
    assert project["id"] in {item["id"] for item in visible_again.json()}

    missing = await async_client.post("/v1/workspace/projects/missing/archive", json={"expected_revision": 1})
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_stale_workspace_project_archive_cannot_restore_or_rearchive(async_client):
    created = await async_client.post("/v1/workspace/projects", json={"name": "Concurrent archive"})
    assert created.status_code == 201
    project = created.json()

    archived = await async_client.post(
        f"/v1/workspace/projects/{project['id']}/archive", json={"expected_revision": project["revision"]}
    )
    assert archived.status_code == 200

    stale_restore = await async_client.post(
        f"/v1/workspace/projects/{project['id']}/restore", json={"expected_revision": project["revision"]}
    )
    assert stale_restore.status_code == 409
    assert stale_restore.json()["detail"]["code"] == "WorkspaceProjectRevisionConflict"
    assert stale_restore.json()["detail"]["current_revision"] == archived.json()["revision"]

    current = await async_client.get("/v1/workspace/projects", params={"include_archived": True})
    stored = next(item for item in current.json() if item["id"] == project["id"])
    assert stored["archived_at"] == archived.json()["archived_at"]
    assert stored["revision"] == archived.json()["revision"]


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
