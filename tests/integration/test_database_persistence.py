"""Integration tests for database persistence across re-queries."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MessageModel, RunEventModel, RunModel, SessionModel
from app.observability.tracer import TraceService


@pytest.mark.asyncio
async def test_full_run_and_event_persistence(test_db_session: AsyncSession):
    session_id = "integration-sess-1"
    run_id = "integration-run-1"

    # 1. Create Session
    session = SessionModel(id=session_id, title="Integration Test Session")
    test_db_session.add(session)

    # 2. Create Run
    run = RunModel(
        id=run_id,
        session_id=session_id,
        status="running",
        user_message="Test run message",
    )
    test_db_session.add(run)

    # 3. Create Messages
    msg = MessageModel(session_id=session_id, role="user", content="Test run message")
    test_db_session.add(msg)
    await test_db_session.commit()

    # 4. Use TraceService to log events
    tracer = TraceService(test_db_session)
    await tracer.record_event(run_id=run_id, event_type="request_received", payload={"step": 1})
    await tracer.record_event(run_id=run_id, event_type="model_called", payload={"tokens": 42})

    # 5. Query back from fresh query
    run_result = await test_db_session.execute(select(RunModel).where(RunModel.id == run_id))
    fetched_run = run_result.scalar_one()
    assert fetched_run.session_id == session_id
    assert fetched_run.status == "running"

    events = await tracer.get_run_events(run_id)
    assert len(events) == 2
    assert events[0].event_type == "request_received"
    assert events[1].event_type == "model_called"


@pytest.mark.asyncio
async def test_trace_service_orders_equal_timestamps_deterministically(test_db_session: AsyncSession):
    session = SessionModel(id="tie-session", title="Tie")
    run = RunModel(id="tie-run", session_id=session.id, status="completed", user_message="trace")
    event_time = datetime.now(timezone.utc)
    test_db_session.add_all([
        session,
        run,
        RunEventModel(id="event-z", run_id=run.id, event_type="later-id", payload={}, created_at=event_time),
        RunEventModel(id="event-a", run_id=run.id, event_type="earlier-id", payload={}, created_at=event_time),
    ])
    await test_db_session.commit()

    events = await TraceService(test_db_session).get_run_events(run.id)

    assert [event.id for event in events] == ["event-a", "event-z"]
