"""Active Automation cancellation through the API and durable root runtime."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.server import app
from app.db.base import Base
from app.db.models import EventRecordModel, EventStatus, RunEventModel, RunModel, utc_now
from app.db.session import get_db
from app.events.dispatcher import EventToAgentBridge
from app.events.types import AURAEvent
from app.models.base import ModelResponse


@pytest.mark.asyncio
async def test_active_automation_stop_is_observed_after_inflight_model_call(async_client, tmp_path, monkeypatch):
    database_path = tmp_path / "automation-cancellation.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def independent_db_sessions():
        async with factory() as session:
            yield session

    previous_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = independent_db_sessions
    model_call_started = asyncio.Event()
    release_model_call = asyncio.Event()

    async def slow_model_call(_request, provider_name=None):
        model_call_started.set()
        await release_model_call.wait()
        return ModelResponse(content="The in-flight answer must not be reported as completed.")

    monkeypatch.setattr("app.models.router.model_router.route", slow_model_call)

    try:
        created = await async_client.post("/v1/automations", json={
            "name": "Stop active automation",
            "instruction": "Pause while a local model is working.",
            "interval_seconds": 3600,
        })
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]
        queued = await async_client.post(f"/v1/automations/{automation_id}/run")
        assert queued.status_code == 202, queued.text

        async with factory() as session:
            record = await session.get(EventRecordModel, queued.json()["event_id"])
            record.status = EventStatus.PROCESSING.value
            record.locked_at = utc_now()
            record.locked_by = "automation-worker"
            await session.commit()
            event = AURAEvent(
                id=record.id,
                event_type=record.event_type,
                source=record.source,
                payload=record.payload_json,
                occurred_at=record.occurred_at,
                correlation_id=record.correlation_id,
                idempotency_key=record.idempotency_key,
                status=EventStatus.PROCESSING,
                retry_count=record.retry_count,
                max_attempts=record.max_attempts,
            )

        dispatch_task = asyncio.create_task(EventToAgentBridge(session_factory=factory).handle_event(event))
        await asyncio.wait_for(model_call_started.wait(), timeout=5)

        cancel = await async_client.post(
            f"/v1/automations/{automation_id}/runs/{event.id}/cancel"
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "cancellation_requested"
        release_model_call.set()

        final_state = await asyncio.wait_for(dispatch_task, timeout=5)
        assert final_state["execution_status"] == "cancelled"
        assert "must not be reported as completed" not in final_state["final_response"]

        async with factory() as session:
            run = await session.get(RunModel, cancel.json()["run_id"])
            assert run.status == "cancelled"
            assert run.cancel_requested_at is not None
            events = list((await session.scalars(
                select(RunEventModel).where(RunEventModel.run_id == run.id)
            )).all())
            assert {item.event_type for item in events} >= {
                "run_cancellation_requested",
                "run_cancelled",
            }
    finally:
        release_model_call.set()
        app.dependency_overrides[get_db] = previous_override
        await engine.dispose()


@pytest.mark.asyncio
async def test_stop_racing_dispatcher_finalization_is_never_reported_as_accepted_and_ignored(
    async_client, tmp_path, monkeypatch
):
    database_path = tmp_path / "automation-cancellation-finalize-race.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def independent_db_sessions():
        async with factory() as session:
            yield session

    previous_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = independent_db_sessions
    model_call_started = asyncio.Event()
    release_model_call = asyncio.Event()
    status_read = asyncio.Event()
    release_finalization = asyncio.Event()
    original_refresh = AsyncSession.refresh

    async def slow_model_call(_request, provider_name=None):
        model_call_started.set()
        await release_model_call.wait()
        return ModelResponse(content="The answer is ready.")

    async def pause_after_status_read(session, instance, *args, **kwargs):
        result = await original_refresh(session, instance, *args, **kwargs)
        if isinstance(instance, RunModel) and instance.user_message == "race at finalization":
            status_read.set()
            await release_finalization.wait()
        return result

    monkeypatch.setattr("app.models.router.model_router.route", slow_model_call)
    monkeypatch.setattr(AsyncSession, "refresh", pause_after_status_read)

    try:
        created = await async_client.post("/v1/automations", json={
            "name": "Stop at finalization",
            "instruction": "race at finalization",
            "interval_seconds": 3600,
        })
        assert created.status_code == 201, created.text
        automation_id = created.json()["id"]
        queued = await async_client.post(f"/v1/automations/{automation_id}/run")
        assert queued.status_code == 202, queued.text

        async with factory() as session:
            record = await session.get(EventRecordModel, queued.json()["event_id"])
            record.status = EventStatus.PROCESSING.value
            record.locked_at = utc_now()
            record.locked_by = "automation-worker"
            await session.commit()
            event = AURAEvent(
                id=record.id,
                event_type=record.event_type,
                source=record.source,
                payload=record.payload_json,
                occurred_at=record.occurred_at,
                correlation_id=record.correlation_id,
                idempotency_key=record.idempotency_key,
                status=EventStatus.PROCESSING,
                retry_count=record.retry_count,
                max_attempts=record.max_attempts,
            )

        dispatch_task = asyncio.create_task(EventToAgentBridge(session_factory=factory).handle_event(event))
        await asyncio.wait_for(model_call_started.wait(), timeout=5)
        release_model_call.set()
        await asyncio.wait_for(status_read.wait(), timeout=5)

        cancel = await async_client.post(
            f"/v1/automations/{automation_id}/runs/{event.id}/cancel"
        )
        release_finalization.set()
        final_state = await asyncio.wait_for(dispatch_task, timeout=5)

        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "cancellation_requested"
        assert final_state["execution_status"] == "cancelled"

        async with factory() as session:
            run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))
            run = await session.get(RunModel, run_id)
            assert run.status == "cancelled"
            assert run.cancel_requested_at is not None
            assert run.final_response.startswith("Run cancelled.")
    finally:
        release_model_call.set()
        release_finalization.set()
        app.dependency_overrides[get_db] = previous_override
        await engine.dispose()
