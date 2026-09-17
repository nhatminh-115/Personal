"""Unit tests for EventBus, transactional outbox persistence, and handler dispatching."""

import pytest
from app.db.models import EventRecordModel, EventStatus
from app.events.bus import EventBus
from app.events.types import AURAEvent, EventType


@pytest.mark.asyncio
async def test_event_bus_subscribe_and_dispatch():
    """Verify EventBus dispatches events to registered typed and wildcard handlers."""
    bus = EventBus()
    received_typed = []
    received_wildcard = []

    async def typed_handler(evt: AURAEvent):
        received_typed.append(evt)

    async def wildcard_handler(evt: AURAEvent):
        received_wildcard.append(evt)

    bus.subscribe(EventType.TIMER_FIRED.value, typed_handler)
    bus.subscribe("*", wildcard_handler)

    test_event = AURAEvent(
        event_type=EventType.TIMER_FIRED.value,
        payload={"task": "health_check"},
    )
    await bus.publish(test_event)

    assert len(received_typed) == 1
    assert received_typed[0].payload["task"] == "health_check"
    assert len(received_wildcard) == 1

    # Unsubscribe typed handler
    bus.unsubscribe(EventType.TIMER_FIRED.value, typed_handler)
    await bus.publish(test_event)

    assert len(received_typed) == 1  # Unchanged
    assert len(received_wildcard) == 2  # Wildcard still received


@pytest.mark.asyncio
async def test_event_bus_transactional_outbox_persistence(test_db_session):
    """Verify published events are durably recorded in the database outbox table."""
    bus = EventBus()

    test_event = AURAEvent(
        event_type=EventType.WEBHOOK_RECEIVED.value,
        source="github_webhook",
        payload={"action": "push", "ref": "refs/heads/main"},
        correlation_id="corr-12345",
    )

    published = await bus.publish(test_event, db=test_db_session)
    assert published.status == EventStatus.PROCESSED

    # Verify database row
    db_record = await test_db_session.get(EventRecordModel, test_event.id)
    assert db_record is not None
    assert db_record.event_type == EventType.WEBHOOK_RECEIVED.value
    assert db_record.source == "github_webhook"
    assert db_record.payload_json["action"] == "push"
    assert db_record.status == EventStatus.PROCESSED.value
    assert db_record.processed_at is not None
    assert db_record.correlation_id == "corr-12345"


@pytest.mark.asyncio
async def test_event_bus_handler_failure_isolation(test_db_session):
    """Verify handler exceptions are recorded as failures in DB outbox without crashing the bus."""
    bus = EventBus()

    async def exploding_handler(evt: AURAEvent):
        raise RuntimeError("Simulated listener exception!")

    bus.subscribe("crash.event", exploding_handler)

    failing_event = AURAEvent(
        event_type="crash.event",
        payload={"data": "test"},
    )

    published = await bus.publish(failing_event, db=test_db_session)
    assert published.status == EventStatus.FAILED

    db_record = await test_db_session.get(EventRecordModel, failing_event.id)
    assert db_record is not None
    assert db_record.status == EventStatus.FAILED.value
    assert db_record.retry_count == 1
    assert "Simulated listener exception" in db_record.error_message
