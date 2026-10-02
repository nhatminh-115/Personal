"""Integration tests for PersistentScheduler, restart durability, and EventToAgentBridge."""

import asyncio
from datetime import timedelta
import pytest
from app.db.models import JobType, ScheduledJobModel, utc_now
from app.events.bus import EventBus
from app.events.dispatcher import EventToAgentBridge
from app.events.scheduler import PersistentScheduler
from app.events.types import AURAEvent, EventType


@pytest.mark.asyncio
async def test_scheduler_one_shot_lifecycle_and_tick(test_db_session):
    """Verify one-shot timer persistence, execution on tick, and deactivation."""
    bus = EventBus()
    scheduler = PersistentScheduler(bus=bus)
    received_events = []

    async def on_timer(evt: AURAEvent):
        received_events.append(evt)

    bus.subscribe(EventType.TIMER_FIRED.value, on_timer)

    # 1. Schedule one-shot timer with negative/zero delay so it is immediately due
    job = await scheduler.schedule_one_shot(
        name="test_backup",
        delay_seconds=-1.0,
        payload={"action": "backup", "target": "memories"},
        db=test_db_session,
    )
    assert job.id is not None
    assert job.is_active is True
    assert job.job_type == JobType.ONE_SHOT.value

    # 2. Tick scheduler -> should trigger job
    emitted = await scheduler.tick(test_db_session)
    assert len(emitted) == 1
    assert emitted[0].event_type == EventType.TIMER_FIRED.value
    assert emitted[0].payload["action"] == "backup"

    assert len(received_events) == 1

    # 3. Check DB state: job should be deactivated
    updated_job = await test_db_session.get(ScheduledJobModel, job.id)
    assert updated_job.is_active is False
    assert updated_job.last_run_at is not None

    # 4. Subsequent tick should not trigger already executed job
    emitted_again = await scheduler.tick(test_db_session)
    assert len(emitted_again) == 0


@pytest.mark.asyncio
async def test_scheduler_recurring_advancement(test_db_session):
    """Verify recurring schedules advance next_run_at and remain active."""
    bus = EventBus()
    scheduler = PersistentScheduler(bus=bus)

    # Schedule recurring job every 60 seconds, initially due immediately
    job = await scheduler.schedule_recurring(
        name="heartbeat_monitor",
        interval_seconds=60.0,
        payload={"ping": True},
        db=test_db_session,
    )
    # Force next_run_at to past
    job.next_run_at = utc_now() - timedelta(seconds=5)
    await test_db_session.commit()

    emitted = await scheduler.tick(test_db_session)
    assert len(emitted) == 1
    assert emitted[0].event_type == EventType.CRON_TICK.value

    # Check job remains active with advanced next_run_at
    updated_job = await test_db_session.get(ScheduledJobModel, job.id)
    assert updated_job.is_active is True
    next_run = updated_job.next_run_at
    if next_run.tzinfo is None:
        from datetime import timezone
        next_run = next_run.replace(tzinfo=timezone.utc)
    assert next_run > utc_now()


@pytest.mark.asyncio
async def test_scheduler_processes_due_jobs_in_bounded_ordered_batches(test_db_session, monkeypatch):
    import app.events.scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "MAX_DUE_JOBS_PER_TICK", 2)
    scheduler = PersistentScheduler(bus=EventBus())
    due_time = utc_now() - timedelta(seconds=5)
    jobs = [
        ScheduledJobModel(
            name=f"batch-job-{index}",
            job_type=JobType.ONE_SHOT.value,
            schedule_expression="5",
            payload_json={"job_index": index},
            is_active=True,
            next_run_at=due_time + timedelta(seconds=index),
            metadata_json={},
        )
        for index in range(5)
    ]
    test_db_session.add_all(jobs)
    await test_db_session.commit()

    first = await scheduler.tick(test_db_session, dispatch_immediate=False)
    assert [event.payload["job_index"] for event in first] == [0, 1]
    assert sum(job.is_active for job in jobs) == 3

    second = await scheduler.tick(test_db_session, dispatch_immediate=False)
    third = await scheduler.tick(test_db_session, dispatch_immediate=False)
    assert [event.payload["job_index"] for event in second + third] == [2, 3, 4]
    assert not any(job.is_active for job in jobs)


@pytest.mark.asyncio
async def test_scheduler_defers_automation_while_prior_run_waits_for_approval(test_db_session):
    """A recurring Automation must not queue again while its prior run is paused for approval."""
    import uuid
    from sqlalchemy import select
    from app.db.models import EventRecordModel, RunModel, RunStatus, SessionModel

    bus = EventBus()
    scheduler = PersistentScheduler(bus=bus)
    automation_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event_id}"))
    job = ScheduledJobModel(
        id=automation_id,
        name="Approval routine",
        job_type=JobType.RECURRING.value,
        schedule_expression="60",
        payload_json={"automation_id": automation_id, "session_id": session_id, "message": "Update the project status."},
        is_active=True,
        next_run_at=utc_now() - timedelta(seconds=1),
        metadata_json={"kind": "automation"},
    )
    test_db_session.add_all([
        job,
        SessionModel(id=session_id, title="Automation run", metadata_json={}),
        EventRecordModel(
            id=event_id,
            event_type=EventType.TIMER_FIRED.value,
            source="automation",
            payload_json=job.payload_json,
            status="processed",
            correlation_id=automation_id,
            idempotency_key=f"manual-{event_id}",
        ),
        RunModel(
            id=run_id,
            session_id=session_id,
            status=RunStatus.WAITING_FOR_APPROVAL.value,
            user_message="Update the project status.",
        ),
    ])
    await test_db_session.commit()

    emitted = await scheduler.tick(test_db_session, dispatch_immediate=False)
    refreshed_job = await test_db_session.get(ScheduledJobModel, automation_id)
    events = list((await test_db_session.execute(
        select(EventRecordModel).where(EventRecordModel.correlation_id == automation_id)
    )).scalars())

    assert emitted == []
    assert refreshed_job is not None
    next_run = refreshed_job.next_run_at
    if next_run.tzinfo is None:
        from datetime import timezone
        next_run = next_run.replace(tzinfo=timezone.utc)
    assert next_run > utc_now()
    assert refreshed_job.locked_at is None
    assert len(events) == 1


@pytest.mark.asyncio
async def test_scheduler_restart_durability(test_db_session):
    """Verify that jobs scheduled before a simulated system restart survive and execute correctly."""
    bus1 = EventBus()
    scheduler1 = PersistentScheduler(bus=bus1)

    # Schedule job that is due
    job = await scheduler1.schedule_one_shot(
        name="pre_restart_job",
        delay_seconds=-10.0,
        payload={"instruction": "verify restart"},
        db=test_db_session,
    )
    job_id = job.id

    # --- SIMULATE PROCESS RESTART ---
    # Create entirely new bus and scheduler instance
    bus2 = EventBus()
    scheduler2 = PersistentScheduler(bus=bus2)
    captured_restart_events = []

    bus2.subscribe("*", lambda evt: captured_restart_events.append(evt) or asyncio.sleep(0))

    # New scheduler ticks on existing database
    emitted = await scheduler2.tick(test_db_session)
    assert len(emitted) == 1
    assert emitted[0].correlation_id == job_id
    assert emitted[0].payload["instruction"] == "verify restart"

    # Verify job is now inactive
    refreshed = await test_db_session.get(ScheduledJobModel, job_id)
    assert refreshed.is_active is False


@pytest.mark.asyncio
async def test_event_to_agent_bridge_triggers_orchestrator(test_db_session):
    """Verify EventToAgentBridge deterministically triggers Personal Orchestrator from an event."""
    from app.orchestrator.graph import get_compiled_graph

    # Mock session factory yielding test_db_session
    class MockSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return test_db_session

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    bridge = EventToAgentBridge(session_factory=MockSessionFactory())

    trigger_event = AURAEvent(
        event_type=EventType.TIMER_FIRED.value,
        source="scheduler",
        payload={
            "session_id": "scheduled-session-101",
            "message": "Hello from scheduled event trigger!",
        },
    )

    final_state = await bridge.handle_event(trigger_event)
    assert final_state is not None
    assert final_state.get("execution_status") == "completed"
    assert final_state.get("final_response") is not None
    assert "AURA Response" in final_state.get("final_response")
