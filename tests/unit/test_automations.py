from datetime import timedelta
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import EventRecordModel, JobType, RunModel, ScheduledJobModel, utc_now
from app.events.dispatcher import EventToAgentBridge
from app.events.types import AURAEvent, EventType


@pytest.mark.asyncio
async def test_automation_crud_and_manual_run_are_persisted(async_client, test_db_session):
    created = await async_client.post("/v1/automations", json={
        "name": "Daily digest",
        "description": "Summarize updates",
        "instruction": "Summarize new project updates and list the next action.",
        "scope": "project",
        "project_name": "AURA",
        "interval_seconds": 86400,
    })
    assert created.status_code == 201, created.text
    automation = created.json()
    assert automation["enabled"] is True
    assert automation["scope"] == "project"
    assert automation["project_name"] == "AURA"
    assert automation["interval_seconds"] == 86400

    job = await test_db_session.get(ScheduledJobModel, automation["id"])
    assert job is not None
    assert job.job_type == JobType.RECURRING.value
    assert job.payload_json["message"] == "Summarize new project updates and list the next action."
    assert job.payload_json["project_name"] == "AURA"
    assert job.metadata_json["kind"] == "automation"

    listed = await async_client.get("/v1/automations")
    assert [record["id"] for record in listed.json()] == [automation["id"]]

    queued = await async_client.post(f"/v1/automations/{automation['id']}/run")
    assert queued.status_code == 202, queued.text
    event = await test_db_session.get(EventRecordModel, queued.json()["event_id"])
    assert event is not None
    assert event.status == "pending"
    assert event.payload_json["automation_id"] == automation["id"]


@pytest.mark.asyncio
async def test_pausing_automation_moves_next_run_and_blocks_manual_run(async_client, test_db_session):
    created = await async_client.post("/v1/automations", json={
        "name": "Routine",
        "instruction": "Review the project status.",
        "interval_seconds": 3600,
    })
    automation_id = created.json()["id"]

    paused = await async_client.put(f"/v1/automations/{automation_id}", json={"enabled": False})
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    run = await async_client.post(f"/v1/automations/{automation_id}/run")
    assert run.status_code == 409

    resumed = await async_client.put(f"/v1/automations/{automation_id}", json={"enabled": True})
    assert resumed.status_code == 200
    assert resumed.json()["enabled"] is True
    assert resumed.json()["next_run_at"]


@pytest.mark.asyncio
async def test_automation_rejects_missing_project_or_blank_instruction(async_client):
    missing_project = await async_client.post("/v1/automations", json={
        "name": "Routine", "instruction": "Do something", "scope": "project", "interval_seconds": 60,
    })
    blank_instruction = await async_client.post("/v1/automations", json={
        "name": "Routine", "instruction": "   ", "interval_seconds": 60,
    })
    assert missing_project.status_code == 422
    assert blank_instruction.status_code == 422


@pytest.mark.asyncio
async def test_automation_list_excludes_non_automation_jobs(async_client, test_db_session):
    test_db_session.add(ScheduledJobModel(
        name="Internal timer", job_type=JobType.ONE_SHOT.value, schedule_expression="60",
        payload_json={}, is_active=True, next_run_at=utc_now() + timedelta(minutes=1), metadata_json={"kind": "internal"},
    ))
    await test_db_session.commit()
    response = await async_client.get("/v1/automations")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_event_bridge_skips_duplicate_delivery_for_existing_run(test_db_session):
    event_id = str(uuid.uuid4())
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event_id}"))
    test_db_session.add(RunModel(
        id=run_id, session_id=str(uuid.uuid4()), status="completed", user_message="Review the workspace.",
    ))
    await test_db_session.commit()
    factory = async_sessionmaker(test_db_session.bind, class_=AsyncSession, expire_on_commit=False)
    bridge = EventToAgentBridge(session_factory=factory)
    event = AURAEvent(id=event_id, event_type=EventType.TIMER_FIRED.value, payload={"message": "Review the workspace."})

    duplicate = await bridge.handle_event(event)
    assert duplicate == {"run_id": run_id, "execution_status": "completed"}
