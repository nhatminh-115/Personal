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
