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
    """Verify published events are durably recorded in the database outbox table as PENDING."""
    bus = EventBus()

    test_event = AURAEvent(
        event_type=EventType.WEBHOOK_RECEIVED.value,
        source="github_webhook",
        payload={"action": "push", "ref": "refs/heads/main"},
        correlation_id="corr-12345",
    )

    published = await bus.publish(test_event, db=test_db_session)
    assert published.status == EventStatus.PENDING

    # Verify database row is pending for OutboxWorker pickup
    db_record = await test_db_session.get(EventRecordModel, test_event.id)
    assert db_record is not None
    assert db_record.event_type == EventType.WEBHOOK_RECEIVED.value
    assert db_record.source == "github_webhook"
    assert db_record.payload_json["action"] == "push"
    assert db_record.status == EventStatus.PENDING.value
    assert db_record.correlation_id == "corr-12345"


@pytest.mark.asyncio
async def test_event_bus_handler_failure_isolation(test_db_session, monkeypatch):
    """Verify handler exceptions are recorded as failures in DB outbox when dispatch_immediate is enabled."""
    from unittest.mock import Mock, call

    bus = EventBus()
    private_diagnostic = "private listener diagnostic token=event-secret"
    log_error = Mock()
    monkeypatch.setattr("app.events.bus.logger.error", log_error)

    async def exploding_handler(evt: AURAEvent):
        raise RuntimeError(private_diagnostic)

    bus.subscribe("crash.event", exploding_handler)

    failing_event = AURAEvent(
        event_type="crash.event",
        payload={"data": "test"},
    )

    published = await bus.publish(failing_event, db=test_db_session, dispatch_immediate=True)
    assert published.status == EventStatus.FAILED

    db_record = await test_db_session.get(EventRecordModel, failing_event.id)
    assert db_record is not None
    assert db_record.status == EventStatus.FAILED.value
    assert db_record.retry_count == 1
    assert db_record.error_message == private_diagnostic
    assert log_error.call_args_list == [
        call(
            "Event handler failed (error type: %s).",
            "RuntimeError",
            extra={"event_id": failing_event.id, "event_type": "crash.event"},
        )
    ]
    assert private_diagnostic not in repr(log_error.call_args_list)


@pytest.mark.asyncio
async def test_event_bus_redacts_provider_failure_from_logs_and_event_record(test_db_session, monkeypatch):
    from unittest.mock import Mock

    from app.core.errors import MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE, ProviderError

    bus = EventBus()
    private_diagnostic = "private immediate provider body sk-test-sensitive"
    log_error = Mock()
    monkeypatch.setattr("app.events.bus.logger.error", log_error)

    async def failing_handler(_: AURAEvent):
        raise ProviderError(
            f"Provider returned 500: {private_diagnostic}",
            details={"body": private_diagnostic},
        )

    bus.subscribe("immediate-provider-failure.event", failing_handler)
    event = AURAEvent(event_type="immediate-provider-failure.event")

    published = await bus.publish(event, db=test_db_session, dispatch_immediate=True)

    assert published.status == EventStatus.FAILED
    record = await test_db_session.get(EventRecordModel, event.id)
    assert record is not None
    assert record.status == EventStatus.FAILED.value
    assert record.error_message == MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE
    assert private_diagnostic not in record.error_message
    assert log_error.call_count == 1
    assert "model provider error" in log_error.call_args.args[0]
    assert private_diagnostic not in repr(log_error.call_args)
    assert "exc_info" not in log_error.call_args.kwargs
