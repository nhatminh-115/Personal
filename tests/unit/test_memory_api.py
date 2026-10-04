import pytest
from app.db.models import MemoryModel
from app.memory.service import SQLMemoryService


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
        memory_type="project", project_name="Atlas", key="architecture",
        content="Old thesis.", confidence=0.8, is_active=False, metadata_json={},
    )
    current = MemoryModel(
        memory_type="project", project_name="Atlas", key="architecture",
        content="Current thesis.", confidence=0.95, is_active=True, metadata_json={},
    )
    test_db_session.add_all([old, current])
    await test_db_session.commit()

    response = await async_client.patch(
        f"/v1/memory/projects/Atlas/{old.id}", json={"is_active": True}
    )
    assert response.status_code == 409
    assert (await test_db_session.get(MemoryModel, old.id)).is_active is False


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
