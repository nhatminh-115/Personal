from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_imported_library_reference_is_shared_with_project_graph_without_file_content(async_client):
    reference_id = str(uuid4())
    created = await async_client.post("/v1/workspace/library", json={
        "id": reference_id,
        "name": "Methods paper",
        "kind": "PDF",
        "collection": "Research",
        "detail": "Imported local file · methods.pdf",
        "tags": ["methods", "paper"],
        "project_names": ["aura", "transportability"],
        "size": 4096,
        "mime_type": "application/pdf",
    })
    assert created.status_code == 201
    assert created.json()["id"] == reference_id
    assert created.json()["project_names"] == ["aura", "transportability"]

    listed = await async_client.get("/v1/workspace/library")
    assert len(listed.json()) == 1
    assert listed.json()[0]["name"] == "Methods paper"
    assert listed.json()[0]["size"] == 4096

    graph = (await async_client.get("/v1/workspace/projects/aura/graph")).json()
    reference = next(item for item in graph["objects"] if item["id"] == reference_id)
    assert reference["object_type"] == "file_reference"
    assert reference["content"] == ""
    assert reference["metadata_json"]["storage_location"] == "browser_local"

    updated = await async_client.put(f"/v1/workspace/library/{reference_id}", json={
        "name": "Methods paper",
        "kind": "PDF",
        "collection": "Research",
        "detail": "Updated local index metadata",
        "tags": ["methods", "paper", "checked"],
        "project_names": ["aura"],
        "size": 4096,
        "mime_type": "application/pdf",
    })
    assert updated.status_code == 200
    assert updated.json()["project_names"] == ["aura"]
    transport_graph = (await async_client.get("/v1/workspace/projects/transportability/graph")).json()
    assert reference_id not in {item["id"] for item in transport_graph["objects"]}

    removed = await async_client.delete(f"/v1/workspace/library/{reference_id}")
    assert removed.status_code == 204
    assert (await async_client.get("/v1/workspace/library")).json() == []
