"""Unit tests for the Durable Transactional Outbox pattern, worker leasing, and dead-letter queues."""

import asyncio
from datetime import timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventRecordModel, EventStatus, utc_now
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
async def test_outbox_worker_never_dispatches_cancelled_event(test_db_session: AsyncSession):
    """A cancelled queued automation event is terminal and must never be claimed."""
    bus = EventBus()
    worker = OutboxWorker(bus=bus)
    received_events = []

    async def sample_handler(evt: AURAEvent):
        received_events.append(evt)

    bus.subscribe("outbox.test", sample_handler)
    event = AURAEvent(
        event_type="outbox.test",
        source="unit_test",
        payload={"message": "cancelled before execution"},
    )
    await bus.publish(event, db=test_db_session)
    db_rec = await test_db_session.get(EventRecordModel, event.id)
    assert db_rec is not None
    db_rec.status = EventStatus.CANCELLED.value
    await test_db_session.commit()

    assert await worker.process_outbox_batch(db=test_db_session) == 0
    assert received_events == []
    await test_db_session.refresh(db_rec)
    assert db_rec.status == EventStatus.CANCELLED.value


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


@pytest.mark.asyncio
async def test_outbox_provider_failure_is_redacted_from_logs_and_event_record(
    test_db_session: AsyncSession, monkeypatch
):
    from unittest.mock import Mock

    from app.core.errors import MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE, ProviderError

    bus = EventBus()
    worker = OutboxWorker(bus=bus, worker_id="provider-failure-worker")
    private_diagnostic = "private provider body sk-test-sensitive"
    log_error = Mock()
    monkeypatch.setattr("app.events.worker.logger.error", log_error)

    async def failing_handler(_: AURAEvent):
        raise ProviderError(
            f"Provider returned 500: {private_diagnostic}",
            details={"body": private_diagnostic},
        )

    bus.subscribe("provider-failure.event", failing_handler)
    event = AURAEvent(event_type="provider-failure.event", max_attempts=3)
    await bus.publish(event, db=test_db_session)

    assert await worker.process_outbox_batch(test_db_session) == 0
    record = await test_db_session.get(EventRecordModel, event.id)
    assert record is not None
    await test_db_session.refresh(record)
    assert record.status == EventStatus.FAILED.value
    assert record.error_message == MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE
    assert private_diagnostic not in record.error_message
    assert log_error.call_count == 1
    assert "model provider error" in log_error.call_args.args[0]
    assert private_diagnostic not in repr(log_error.call_args)
    assert "exc_info" not in log_error.call_args.kwargs


@pytest.mark.asyncio
async def test_outbox_non_provider_handler_failure_logs_no_exception_text(
    test_db_session: AsyncSession, monkeypatch
):
    from unittest.mock import Mock, call

    bus = EventBus()
    worker = OutboxWorker(bus=bus, worker_id="private-failure-worker")
    private_diagnostic = "private queued listener diagnostic token=outbox-secret"
    log_error = Mock()
    monkeypatch.setattr("app.events.worker.logger.error", log_error)

    async def failing_handler(_: AURAEvent):
        raise RuntimeError(private_diagnostic)

    bus.subscribe("private-failure.event", failing_handler)
    event = AURAEvent(event_type="private-failure.event", max_attempts=3)
    await bus.publish(event, db=test_db_session)

    assert await worker.process_outbox_batch(test_db_session) == 0
    record = await test_db_session.get(EventRecordModel, event.id)
    assert record is not None
    await test_db_session.refresh(record)
    assert record.status == EventStatus.FAILED.value
    assert record.error_message == private_diagnostic
    assert log_error.call_args_list == [
        call(
            "OutboxWorker handler failed (error type: %s).",
            "RuntimeError",
            extra={"event_id": event.id, "worker_id": "private-failure-worker"},
        )
    ]
    assert private_diagnostic not in repr(log_error.call_args_list)
    assert "exc_info" not in log_error.call_args.kwargs


@pytest.mark.asyncio
async def test_outbox_recovers_processing_event_after_worker_lease_expires(test_db_session: AsyncSession):
    bus = EventBus()
    worker = OutboxWorker(bus=bus, worker_id="recovery-worker", lease_duration_seconds=60)
    received = []

    async def handler(event: AURAEvent):
        received.append(event.id)

    bus.subscribe("crash-recovery.event", handler)
    event = EventRecordModel(
        event_type="crash-recovery.event",
        source="unit_test",
        payload_json={"durable": True},
        status=EventStatus.PROCESSING.value,
        occurred_at=utc_now() - timedelta(minutes=3),
        next_attempt_at=utc_now() - timedelta(minutes=3),
        locked_at=utc_now() - timedelta(minutes=2),
        locked_by="crashed-worker",
    )
    actively_claimed = EventRecordModel(
        event_type="crash-recovery.event",
        source="unit_test",
        payload_json={"durable": True},
        status=EventStatus.PROCESSING.value,
        occurred_at=utc_now(),
        next_attempt_at=utc_now(),
        locked_at=utc_now(),
        locked_by="active-worker",
    )
    exhausted = EventRecordModel(
        event_type="crash-recovery.event",
        source="unit_test",
        payload_json={"durable": True},
        status=EventStatus.PROCESSING.value,
        retry_count=2,
        max_attempts=3,
        occurred_at=utc_now() - timedelta(minutes=4),
        next_attempt_at=utc_now() - timedelta(minutes=4),
        locked_at=utc_now() - timedelta(minutes=3),
        locked_by="exhausted-worker",
    )
    test_db_session.add_all([event, actively_claimed, exhausted])
    await test_db_session.commit()

    processed = await worker.process_outbox_batch(test_db_session)

    await test_db_session.refresh(event)
    assert processed == 1
    assert received == [event.id]
    assert event.status == EventStatus.PROCESSED.value
    assert event.retry_count == 1
    assert event.locked_at is None
    assert event.locked_by is None
    assert actively_claimed.status == EventStatus.PROCESSING.value
    assert actively_claimed.locked_by == "active-worker"
    assert exhausted.status == EventStatus.DEAD_LETTER.value
    assert exhausted.retry_count == exhausted.max_attempts
    assert "maximum attempts exceeded" in exhausted.error_message


@pytest.mark.asyncio
async def test_outbox_renews_lease_while_handler_is_running(test_db_session: AsyncSession):
    bus = EventBus()
    worker = OutboxWorker(bus=bus, worker_id="slow-worker", lease_duration_seconds=0.12)
    event = EventRecordModel(
        event_type="slow-handler.event",
        source="unit_test",
        payload_json={},
        status=EventStatus.PENDING.value,
        occurred_at=utc_now(),
        next_attempt_at=utc_now(),
    )
    test_db_session.add(event)
    await test_db_session.commit()
    original_lock = None
    renewed_lock = None

    async def slow_handler(_: AURAEvent):
        nonlocal original_lock, renewed_lock
        original_lock = event.locked_at
        await asyncio.sleep(0.18)
        await test_db_session.refresh(event)
        renewed_lock = event.locked_at

    bus.subscribe("slow-handler.event", slow_handler)
    assert await worker.process_outbox_batch(test_db_session) == 1

    await test_db_session.refresh(event)
    assert original_lock is not None
    assert renewed_lock is not None
    normalized_original = original_lock if original_lock.tzinfo else original_lock.replace(tzinfo=timezone.utc)
    normalized_renewed = renewed_lock if renewed_lock.tzinfo else renewed_lock.replace(tzinfo=timezone.utc)
    assert normalized_renewed > normalized_original
    assert event.status == EventStatus.PROCESSED.value
    assert event.locked_at is None


@pytest.mark.asyncio
async def test_outbox_stale_handler_cannot_ack_event_after_lease_reclaimed(test_db_session: AsyncSession):
    bus = EventBus()
    worker = OutboxWorker(bus=bus, worker_id="old-worker", lease_duration_seconds=60)
    event = EventRecordModel(
        event_type="reclaimed-handler.event",
        source="unit_test",
        payload_json={},
        status=EventStatus.PENDING.value,
        occurred_at=utc_now(),
        next_attempt_at=utc_now(),
    )
    test_db_session.add(event)
    await test_db_session.commit()

    async def handler(_: AURAEvent):
        # Model a second worker reclaiming this event after the old worker's
        # lease expires while its handler is still running.
        await test_db_session.execute(
            update(EventRecordModel)
            .where(EventRecordModel.id == event.id)
            .values(locked_by="new-worker", locked_at=utc_now())
        )
        await test_db_session.commit()

    bus.subscribe("reclaimed-handler.event", handler)
    assert await worker.process_outbox_batch(test_db_session) == 0

    await test_db_session.refresh(event)
    assert event.status == EventStatus.PROCESSING.value
    assert event.locked_by == "new-worker"
    assert event.locked_at is not None
