"""Unit tests for the Durable Transactional Outbox pattern, worker leasing, and dead-letter queues."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventRecordModel, EventStatus
from app.events.bus import EventBus
from app.events.types import AURAEvent, EventType
from app.events.worker import OutboxWorker


@pytest.mark.asyncio
async def test_outbox_commit_before_dispatch(test_db_session: AsyncSession):
    """
    Verify producer commit-before-dispatch:
    - publish(event, db) commits row as 'pending'.
    - Handlers are NOT called synchronously.
    - OutboxWorker claims and delivers the event, transitioning to 'processed'.
    """
    bus = EventBus()
    worker = OutboxWorker(bus=bus)
    received_events = []

    async def sample_handler(evt: AURAEvent):
        received_events.append(evt)

    bus.subscribe("outbox.test", sample_handler)

    event = AURAEvent(
        event_type="outbox.test",
        source="unit_test",
        payload={"message": "hello durable outbox"},
    )

    # 1. Producer publishes to outbox
    published = await bus.publish(event, db=test_db_session)
    assert published.status == EventStatus.PENDING
    assert len(received_events) == 0  # NOT executed synchronously

    # Check DB state
    db_rec = await test_db_session.get(EventRecordModel, event.id)
    assert db_rec is not None
    assert db_rec.status == EventStatus.PENDING.value

    # 2. Worker claims and processes outbox
    processed_count = await worker.process_outbox_batch(db=test_db_session)
    assert processed_count == 1
    assert len(received_events) == 1
    assert received_events[0].id == event.id

    # Check updated DB state
    await test_db_session.refresh(db_rec)
    assert db_rec.status == EventStatus.PROCESSED.value
    assert db_rec.processed_at is not None


@pytest.mark.asyncio
async def test_outbox_idempotency_deduplication(test_db_session: AsyncSession):
    """Verify that publishing an event with an existing idempotency_key prevents duplicate entries."""
    bus = EventBus()

    event1 = AURAEvent(
        event_type="payment.processed",
        source="stripe",
        payload={"order_id": 101},
        idempotency_key="unique-stripe-event-101",
    )
    res1 = await bus.publish(event1, db=test_db_session)

    # Second publication with same idempotency key
    event2 = AURAEvent(
        event_type="payment.processed",
        source="stripe",
        payload={"order_id": 101},
        idempotency_key="unique-stripe-event-101",
    )
    res2 = await bus.publish(event2, db=test_db_session)

    assert res2.id == res1.id

    stmt = select(EventRecordModel).where(EventRecordModel.idempotency_key == "unique-stripe-event-101")
    rows = (await test_db_session.execute(stmt)).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_outbox_retry_and_dead_letter_queue(test_db_session: AsyncSession):
    """Verify that repeatedly failing events are retried up to max_attempts and then marked DEAD_LETTER."""
    bus = EventBus()
    worker = OutboxWorker(bus=bus)

    async def failing_handler(evt: AURAEvent):
        raise ValueError("Downstream API timeout")

    bus.subscribe("failing.event", failing_handler)

    event = AURAEvent(
        event_type="failing.event",
        source="unit_test",
        payload={"item": "bad_item"},
        max_attempts=3,
    )
    await bus.publish(event, db=test_db_session)

    db_rec = await test_db_session.get(EventRecordModel, event.id)
    assert db_rec.status == EventStatus.PENDING.value
    assert db_rec.retry_count == 0

    # Attempt 1: fails, status='failed', retry_count=1
    await worker.process_outbox_batch(db=test_db_session)
    await test_db_session.refresh(db_rec)
    assert db_rec.status == EventStatus.FAILED.value
    assert db_rec.retry_count == 1

    # Reset next_attempt_at so it is immediately eligible for attempt 2
    db_rec.next_attempt_at = None
    await test_db_session.commit()

    # Attempt 2: fails, retry_count=2
    await worker.process_outbox_batch(db=test_db_session)
    await test_db_session.refresh(db_rec)
    assert db_rec.status == EventStatus.FAILED.value
    assert db_rec.retry_count == 2

    # Reset next_attempt_at so it is immediately eligible for attempt 3
    db_rec.next_attempt_at = None
    await test_db_session.commit()

    # Attempt 3: exceeds max_attempts=3 -> DEAD_LETTER
    await worker.process_outbox_batch(db=test_db_session)
    await test_db_session.refresh(db_rec)
    assert db_rec.status == EventStatus.DEAD_LETTER.value
    assert db_rec.retry_count == 3
    assert "Downstream API timeout" in db_rec.error_message
