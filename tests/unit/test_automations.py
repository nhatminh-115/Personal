from datetime import timedelta
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import EventRecordModel, JobType, ProjectRoutingAssignmentModel, RunEventModel, RoutingProfileModel, RunModel, ScheduledJobModel, SessionModel, utc_now
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
    latest = (await async_client.get("/v1/automations")).json()[0]["latest_execution"]
    assert latest["event_id"] == event.id
    assert latest["status"] == "queued"
    assert latest["run_id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))


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
async def test_automation_status_tracks_persisted_root_run_state(async_client, test_db_session):
    created = await async_client.post("/v1/automations", json={
        "name": "Approval routine", "instruction": "Update the project plan.", "interval_seconds": 3600,
    })
    automation_id = created.json()["id"]
    queued = await async_client.post(f"/v1/automations/{automation_id}/run")
    event_id = queued.json()["event_id"]
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event_id}"))
    session_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id, title="Automation run", metadata_json={}))
    test_db_session.add(RunModel(
        id=run_id, session_id=session_id, status="waiting_for_approval", user_message="Update the project plan.",
    ))
    await test_db_session.commit()

    listed = await async_client.get("/v1/automations")
    latest = listed.json()[0]["latest_execution"]
    assert latest["event_id"] == event_id
    assert latest["run_id"] == run_id
    assert latest["status"] == "waiting_for_approval"


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



@pytest.mark.asyncio
async def test_automation_event_uses_effective_project_profile_but_stays_local_only(test_db_session, monkeypatch):
    from unittest.mock import AsyncMock

    profile_id = "automation-cloud-profile"
    test_db_session.add(RoutingProfileModel(
        id=profile_id,
        name="Cloud allowed project profile",
        global_privacy_policy="public",
        global_fallback_policy="cloud_allowed",
        is_active=True,
        is_default=False,
        routes_json={"routes": {"root": {"model_override": "mock:cloud-model"}}},
    ))
    test_db_session.add(ProjectRoutingAssignmentModel(
        project_name="Atlas",
        routing_profile_id=profile_id,
    ))
    await test_db_session.commit()

    observed = {}
    mock_graph = AsyncMock()

    async def invoke(initial_state, config):
        observed["state"] = initial_state
        return {"execution_status": "completed", "final_response": "Automation completed."}

    mock_graph.ainvoke.side_effect = invoke
    monkeypatch.setattr("app.events.dispatcher.get_compiled_graph", AsyncMock(return_value=mock_graph))

    event_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    factory = async_sessionmaker(test_db_session.bind, class_=AsyncSession, expire_on_commit=False)
    bridge = EventToAgentBridge(session_factory=factory)
    event = AURAEvent(
        id=event_id,
        event_type=EventType.TIMER_FIRED.value,
        payload={
            "message": "Review Atlas.",
            "automation_id": "automation-atlas",
            "project_name": "Atlas",
            "session_id": session_id,
        },
    )

    result = await bridge.handle_event(event)
    assert result["execution_status"] == "completed"

    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event_id}"))
    run_record = await test_db_session.get(RunModel, run_id)
    assert run_record is not None
    assert run_record.routing_snapshot_json["profile_id"] == profile_id
    assert run_record.routing_snapshot_json["winning_scope"] == "project"
    assert run_record.routing_snapshot_json["privacy_policy"] == "local_only"
    assert run_record.routing_snapshot_json["fallback_policy"] == "local_only"

    routing_context = observed["state"]["metadata"]["routing_context_dict"]
    assert routing_context["privacy_requirement"] == "local_only"
    assert routing_context["fallback_policy"] == "local_only"
    assert routing_context["explicit_model_override"] == "mock:cloud-model"
    assert observed["state"]["project_name"] == "Atlas"

    session_record = await test_db_session.get(SessionModel, session_id)
    assert session_record is not None
    assert session_record.project_name == "Atlas"

    routing_events = (await test_db_session.execute(
        __import__("sqlalchemy").select(RunEventModel).where(
            RunEventModel.run_id == run_id,
            RunEventModel.event_type == "routing_profile_resolved",
        )
    )).scalars().all()
    assert len(routing_events) == 1
    assert routing_events[0].payload_json["privacy_policy"] == "local_only"
