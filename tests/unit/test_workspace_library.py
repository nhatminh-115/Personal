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
    project_search = await async_client.get("/v1/workspace/library", params={"q": "methods", "project_name": "transportability"})
    assert [item["id"] for item in project_search.json()] == [reference_id]
    unrelated_project_search = await async_client.get("/v1/workspace/library", params={"q": "methods", "project_name": "unknown"})
    assert unrelated_project_search.json() == []

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


@pytest.mark.asyncio
async def test_workspace_library_accepts_docx_reference_metadata(async_client):
    created = await async_client.post("/v1/workspace/library", json={
        "name": "Local report",
        "kind": "DOCX",
        "collection": "Reference",
        "detail": "Imported local Word document",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })

    assert created.status_code == 201
    assert created.json()["kind"] == "DOCX"
    assert created.json()["mime_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.asyncio
async def test_library_search_matches_metadata_and_keeps_cursor_pagination(async_client):
    references = [
        {"id": str(uuid4()), "name": "Alpha paper", "detail": "target in imported detail", "collection": "Research", "tags": []},
        {"id": str(uuid4()), "name": "Target title", "detail": "A local reference", "collection": "Books", "tags": []},
        {"id": str(uuid4()), "name": "Tagged paper", "detail": "Another local reference", "collection": "Reference", "tags": ["target-tag"]},
        {"id": str(uuid4()), "name": "Collection paper", "detail": "Another local reference", "collection": "Study", "tags": []},
        {"id": str(uuid4()), "name": "Unrelated paper", "detail": "No matching metadata", "collection": "Books", "tags": ["misc"]},
    ]
    for item in references:
        response = await async_client.post("/v1/workspace/library", json={
            "id": item["id"], "name": item["name"], "kind": "PDF", "collection": item["collection"],
            "detail": item["detail"], "tags": item["tags"], "project_names": [], "size": 128,
            "mime_type": "application/pdf",
        })
        assert response.status_code == 201

    first = await async_client.get("/v1/workspace/library", params={"q": "target", "page_size": 2})
    first_items = first.json()
    assert len(first_items) == 2
    cursor = first.headers.get("X-Next-Cursor")
    assert cursor

    second = await async_client.get("/v1/workspace/library", params={"q": "target", "page_size": 2, "cursor": cursor})
    second_items = second.json()
    assert len(second_items) == 1
    all_items = first_items + second_items
    assert {item["id"] for item in all_items} == {item["id"] for item in references[:3]}
    assert not ({item["id"] for item in first_items} & {item["id"] for item in second_items})
    assert all(item["detail"] != "" for item in all_items)

    collection_match = await async_client.get("/v1/workspace/library", params={"q": "research"})
    assert [item["id"] for item in collection_match.json()] == [references[0]["id"]]


@pytest.mark.asyncio
async def test_library_search_escapes_sql_wildcards_and_rejects_blank_query(async_client):
    await async_client.post("/v1/workspace/library", json={
        "id": str(uuid4()), "name": "100% local", "kind": "TXT", "collection": "Reference",
        "detail": "Literal title", "tags": ["safe"], "project_names": [],
    })
    assert len((await async_client.get("/v1/workspace/library", params={"q": "%"})).json()) == 1
    assert (await async_client.get("/v1/workspace/library", params={"q": "_"})).json() == []
    assert (await async_client.get("/v1/workspace/library", params={"q": "   "})).status_code == 422


@pytest.mark.asyncio
async def test_library_link_candidates_exclude_references_already_linked_to_project(async_client):
    linked_id, candidate_id, other_linked_id = str(uuid4()), str(uuid4()), str(uuid4())
    for item_id, project_names in (
        (linked_id, ["aura"]),
        (candidate_id, []),
        (other_linked_id, ["another-project"]),
    ):
        response = await async_client.post("/v1/workspace/library", json={
            "id": item_id, "name": "Durable context paper", "kind": "PDF", "collection": "Research",
            "detail": "candidate search phrase", "tags": [], "project_names": project_names,
        })
        assert response.status_code == 201

    candidates = await async_client.get("/v1/workspace/library", params={
        "q": "candidate search", "unlinked_project_name": "aura", "page_size": 1,
    })
    assert len(candidates.json()) == 1
    assert candidates.json()[0]["id"] in {candidate_id, other_linked_id}
    cursor = candidates.headers.get("X-Next-Cursor")
    assert cursor
    next_page = await async_client.get("/v1/workspace/library", params={
        "q": "candidate search", "unlinked_project_name": "aura", "page_size": 1, "cursor": cursor,
    })
    assert len(next_page.json()) == 1
    assert next_page.json()[0]["id"] in {candidate_id, other_linked_id}
    assert next_page.json()[0]["id"] != candidates.json()[0]["id"]
    assert {candidates.json()[0]["id"], next_page.json()[0]["id"]} == {candidate_id, other_linked_id}

    unfiltered = await async_client.get("/v1/workspace/library", params={"q": "candidate search"})
    assert {item["id"] for item in unfiltered.json()} == {linked_id, candidate_id, other_linked_id}

    blank_project = await async_client.get("/v1/workspace/library", params={"unlinked_project_name": "  "})
    assert blank_project.status_code == 422
