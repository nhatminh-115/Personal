import pytest
from app.db.models import MemoryModel
from app.memory.service import SQLMemoryService


@pytest.mark.asyncio
async def test_memory_by_id_requires_project_or_session_scope(async_client, test_db_session):
    project_memory = MemoryModel(
        id="old-project-memory", memory_type="semantic", project_name="Atlas",
        key="prior_constraint", content="Keep the migration reversible.", confidence=0.88,
        is_active=True, metadata_json={},
    )
    episode = MemoryModel(
        id="source-session-episode", memory_type="episodic", session_id="source-session",
        key="completed_run", content="The migration completed after restart.", confidence=0.91,
        is_active=True, metadata_json={},
    )
    other_project_memory = MemoryModel(
        id="other-project-memory", memory_type="semantic", project_name="Borealis",
        key="secret", content="Other project content.", confidence=0.9, is_active=True, metadata_json={},
    )
    test_db_session.add_all([project_memory, episode, other_project_memory])
    await test_db_session.commit()

    missing_scope = await async_client.get(f"/v1/memory/by-id/{project_memory.id}")
    assert missing_scope.status_code == 422

    project_match = await async_client.get(
        f"/v1/memory/by-id/{project_memory.id}", params={"project_name": "Atlas"}
    )
    assert project_match.status_code == 200
    assert project_match.json()["content"] == "Keep the migration reversible."

    wrong_project = await async_client.get(
        f"/v1/memory/by-id/{project_memory.id}", params={"project_name": "Borealis"}
    )
    assert wrong_project.status_code == 404
    assert (await async_client.get(
        f"/v1/memory/by-id/{episode.id}", params={"session_id": "source-session"}
    )).json()["id"] == episode.id
    assert (await async_client.get(
        f"/v1/memory/by-id/{episode.id}", params={"session_id": "other-session"}
    )).status_code == 404


@pytest.mark.asyncio
async def test_profile_memory_by_id_is_limited_to_global_profile_scope(async_client, test_db_session):
    global_memory = MemoryModel(
        id="global-profile-memory", memory_type="profile", project_name=None,
        key="preferred_language", content="Vietnamese", confidence=1.0,
        is_active=True, metadata_json={},
    )
    project_profile_memory = MemoryModel(
        id="project-profile-memory", memory_type="profile", project_name="Atlas",
        key="project_voice", content="Concise", confidence=1.0, is_active=True, metadata_json={},
    )
    test_db_session.add_all([global_memory, project_profile_memory])
    await test_db_session.commit()

    response = await async_client.get(f"/v1/memory/profile/{global_memory.id}")
    assert response.status_code == 200
    assert response.json()["content"] == "Vietnamese"
    assert (await async_client.get(f"/v1/memory/profile/{project_profile_memory.id}")).status_code == 404


@pytest.mark.asyncio
async def test_project_memory_can_be_deactivated_and_restored_without_deletion(async_client, test_db_session):
    memory = MemoryModel(
        memory_type="project",
        project_name="Atlas",
        key="architecture",
        content="Keep project context explicit.",
        confidence=0.9,
        is_active=True,
        metadata_json={},
    )
    test_db_session.add(memory)
    await test_db_session.commit()

    deactivate = await async_client.patch(
        f"/v1/memory/projects/Atlas/{memory.id}",
        json={"is_active": False},
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False
    assert await test_db_session.get(MemoryModel, memory.id) is not None
    assert await SQLMemoryService(test_db_session).get_project_memories("Atlas") == []

    active_listing = await async_client.get(
        "/v1/memory", params={"project_name": "Atlas", "include_inactive": False}
    )
    assert active_listing.status_code == 200
    assert active_listing.json() == []

    history_listing = await async_client.get(
        "/v1/memory", params={"project_name": "Atlas", "include_inactive": True}
    )
    assert history_listing.status_code == 200
    assert [(item["id"], item["is_active"]) for item in history_listing.json()] == [(memory.id, False)]

    restore = await async_client.patch(
        f"/v1/memory/projects/Atlas/{memory.id}",
        json={"is_active": True},
    )
    assert restore.status_code == 200
    assert restore.json()["is_active"] is True
    assert [item.id for item in await SQLMemoryService(test_db_session).get_project_memories("Atlas")] == [memory.id]


@pytest.mark.asyncio
async def test_project_memory_restore_rejects_an_active_replacement(async_client, test_db_session):
    old = MemoryModel(
        id="memory-old",
        memory_type="project", project_name="Atlas", key="architecture",
        content="Old thesis.", confidence=0.8, is_active=False,
        superseded_by_id="memory-current", metadata_json={},
    )
    current = MemoryModel(
        id="memory-current",
        memory_type="project", project_name="Atlas", key="architecture",
        content="Current thesis.", confidence=0.95, is_active=True,
        supersedes_id="memory-old", metadata_json={},
    )
    test_db_session.add_all([old, current])
    await test_db_session.commit()

    response = await async_client.patch(
        f"/v1/memory/projects/Atlas/{old.id}", json={"is_active": True}
    )
    assert response.status_code == 409
    assert (await test_db_session.get(MemoryModel, old.id)).is_active is False
    history = await async_client.get(
        "/v1/memory", params={"project_name": "Atlas", "include_inactive": True}
    )
    versions = {item["id"]: item for item in history.json()}
    assert versions["memory-old"]["superseded_by_id"] == "memory-current"
    assert versions["memory-current"]["supersedes_id"] == "memory-old"


@pytest.mark.asyncio
async def test_project_memory_lifecycle_endpoint_is_scoped_and_hides_non_project_memories(async_client, test_db_session):
    memory = MemoryModel(
        memory_type="semantic", project_name="Atlas", key="general",
        content="A global fact.", confidence=1.0, is_active=True, metadata_json={},
    )
    test_db_session.add(memory)
    await test_db_session.commit()

    wrong_project = await async_client.patch(
        f"/v1/memory/projects/Other/{memory.id}", json={"is_active": False}
    )
    assert wrong_project.status_code == 404
    wrong_type = await async_client.patch(
        f"/v1/memory/projects/Atlas/{memory.id}", json={"is_active": False}
    )
    assert wrong_type.status_code == 404
    assert memory.is_active is True


@pytest.mark.asyncio
async def test_personal_profile_memory_can_be_deactivated_restored_and_filtered(async_client, test_db_session):
    memory = MemoryModel(
        memory_type="profile", project_name=None, key="preferred_language",
        content="Vietnamese", confidence=1.0, is_active=True, metadata_json={},
    )
    project_memory = MemoryModel(
        memory_type="profile", project_name="Atlas", key="project_only",
        content="This belongs to Atlas.", confidence=1.0, is_active=True, metadata_json={},
    )
    test_db_session.add_all([memory, project_memory])
    await test_db_session.commit()

    listing = await async_client.get("/v1/memory", params={"memory_type": "profile", "include_inactive": True})
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [memory.id]

    deactivate = await async_client.patch(f"/v1/memory/profile/{memory.id}", json={"is_active": False})
    assert deactivate.status_code == 200
    assert await SQLMemoryService(test_db_session).get_profile_fact("preferred_language") is None

    restore = await async_client.patch(f"/v1/memory/profile/{memory.id}", json={"is_active": True})
    assert restore.status_code == 200
    assert await SQLMemoryService(test_db_session).get_profile_fact("preferred_language") == "Vietnamese"


@pytest.mark.asyncio
async def test_profile_restore_rejects_superseded_duplicate_and_wrong_scope(async_client, test_db_session):
    archived = MemoryModel(
        memory_type="profile", key="preferred_language", content="Vietnamese",
        confidence=1.0, is_active=False, metadata_json={},
    )
    active = MemoryModel(
        memory_type="profile", key="preferred_language", content="English",
        confidence=1.0, is_active=True, metadata_json={},
    )
    project_scoped = MemoryModel(
        memory_type="profile", project_name="Atlas", key="editor", content="VS Code",
        confidence=1.0, is_active=True, metadata_json={},
    )
    test_db_session.add_all([archived, active, project_scoped])
    await test_db_session.commit()

    conflict = await async_client.patch(f"/v1/memory/profile/{archived.id}", json={"is_active": True})
    assert conflict.status_code == 409
    wrong_scope = await async_client.patch(f"/v1/memory/profile/{project_scoped.id}", json={"is_active": False})
    assert wrong_scope.status_code == 404
    assert (await test_db_session.get(MemoryModel, active.id)).is_active is True
