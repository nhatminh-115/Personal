"""Integration tests for database persistence across re-queries."""

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
