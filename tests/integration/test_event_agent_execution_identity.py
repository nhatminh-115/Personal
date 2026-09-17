"""Integration tests verifying isolated execution identities for proactive Event -> Agent runs."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RunModel, RunStatus
from app.events.dispatcher import EventToAgentBridge
from app.events.types import AURAEvent, EventType


@pytest.mark.asyncio
async def test_event_agent_isolated_execution_identity(test_db_session: AsyncSession):
    """
    Verify that multiple events belonging to the same session use unique thread_ids (run_id),
    ensuring that a suspended event waiting for approval does not block or corrupt other event runs.
    """
    engine = test_db_session.bind
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    bridge = EventToAgentBridge(session_factory=session_factory)
    shared_session_id = "session-proactive-shared"

    # 1. Event 1: Normal conversational query
    event1 = AURAEvent(
        event_type=EventType.TIMER_FIRED.value,
        payload={
            "session_id": shared_session_id,
            "message": "Hello AURA, please do your routine check.",
        },
    )
    res1 = await bridge.handle_event(event1)
    assert res1 is not None
    assert res1.get("execution_status") == RunStatus.COMPLETED.value
    run1_id = res1["run_id"]

    # 2. Event 2: High-risk mutation requiring approval in the SAME session
    event2 = AURAEvent(
        event_type=EventType.WEBHOOK_RECEIVED.value,
        payload={
            "session_id": shared_session_id,
            "message": "Write webhook payload to alert.log",
        },
    )
    res2 = await bridge.handle_event(event2)
    assert res2 is not None
    run2_id = res2["run_id"]
    assert run1_id != run2_id  # Isolated run IDs

    # Event 2 must be suspended waiting for approval
    assert "__interrupt__" in res2
    assert len(res2["__interrupt__"]) > 0

    # 3. Verify in database:
    # Run 1 completed; Run 2 is waiting_for_approval
    async with session_factory() as verify_db:
        db_run1 = await verify_db.get(RunModel, run1_id)
        db_run2 = await verify_db.get(RunModel, run2_id)

        assert db_run1.status == RunStatus.COMPLETED.value
        assert db_run2.status == RunStatus.WAITING_FOR_APPROVAL.value
        assert "Approval ID:" in db_run2.final_response

    # 4. Event 3: Third event in the SAME session should also execute independently without collision
    event3 = AURAEvent(
        event_type=EventType.CRON_TICK.value,
        payload={
            "session_id": shared_session_id,
            "message": "System ping tick",
        },
    )
    res3 = await bridge.handle_event(event3)
    assert res3 is not None
    assert res3.get("execution_status") == RunStatus.COMPLETED.value
    run3_id = res3["run_id"]
    assert run3_id not in (run1_id, run2_id)
