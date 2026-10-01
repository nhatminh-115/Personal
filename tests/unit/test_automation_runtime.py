from sqlalchemy import select

from app.db.models import EventRecordModel, EventStatus, RunModel
from app.events.dispatcher import EventToAgentBridge
from app.events.types import AURAEvent, EventType


async def test_automation_api_persists_schedule_and_queues_run(async_client, test_db_session):
    created = await async_client.post("/v1/automations", json={
        "name": "  Daily review  ",
        "description": "Review work",
        "message": "Summarize my project progress",
        "project_name": "AURA",
        "interval_seconds": 86400,
    })
    assert created.status_code == 201
    automation = created.json()
    assert automation["name"] == "Daily review"
    assert automation["project_name"] == "AURA"
    assert automation["is_active"] is True

    queued = await async_client.post(f"/v1/automations/{automation['id']}/run")
    assert queued.status_code == 202
    event = await test_db_session.get(EventRecordModel, queued.json()["event_id"])
    assert event is not None
    assert event.status == EventStatus.PENDING.value
    assert event.payload_json["metadata"]["force_local_only"] is True

    paused = await async_client.put(f"/v1/automations/{automation['id']}", json={"is_active": False})
    assert paused.status_code == 200
    blocked_run = await async_client.post(f"/v1/automations/{automation['id']}/run")
    assert blocked_run.status_code == 409

    deleted = await async_client.delete(f"/v1/automations/{automation['id']}")
    assert deleted.status_code == 204
    listed = await async_client.get("/v1/automations")
    assert listed.json() == []


async def test_event_bridge_persists_local_only_snapshot_and_deduplicates(test_db_session, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    import app.events.dispatcher as dispatcher

    factory = async_sessionmaker(test_db_session.bind, expire_on_commit=False)
    invoked = []

    class FakeGraph:
        async def ainvoke(self, initial_state, config):
            invoked.append(initial_state)
            return {"execution_status": "completed", "final_response": "Routine complete"}

    async def fake_graph():
        return FakeGraph()

    monkeypatch.setattr(dispatcher, "get_compiled_graph", fake_graph)
    bridge = EventToAgentBridge(factory)
    event = AURAEvent(
        event_type=EventType.TASK_RESUMED.value,
        source="automation",
        payload={
            "automation_id": "automation-1",
            "session_id": "automation-1",
            "message": "Summarize the workspace",
            "project_name": "AURA",
            "metadata": {"force_local_only": True},
        },
    )

    result = await bridge.handle_event(event)
    duplicate = await bridge.handle_event(event)
    assert result["execution_status"] == "completed"
    assert duplicate["deduplicated"] is True
    assert len(invoked) == 1
    context = invoked[0]["metadata"]["routing_context_dict"]
    assert context["privacy_requirement"] == "local_only"
    assert context["fallback_policy"] == "local_only"

    async with factory() as db:
        runs = list((await db.execute(select(RunModel))).scalars())
        assert len(runs) == 1
        assert runs[0].routing_snapshot_json["privacy_policy"] == "local_only"
        assert runs[0].routing_snapshot_json["fallback_policy"] == "local_only"
