"""Transactional event bus with database outbox persistence and dispatching."""

from collections import defaultdict
from typing import Awaitable, Callable, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import EventRecordModel, EventStatus, utc_now
from app.events.types import AURAEvent

EventHandler = Callable[[AURAEvent], Awaitable[None]]


class EventBus:
    """
    Central event broker implementing the Transactional Outbox pattern:
    - Guarantees durable event persistence in PostgreSQL / SQLite before dispatch.
    - Dispatches to registered async listeners.
    - Tracks delivery, retry attempts, and failure status.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register an async handler for an event type (or '*' for all events)."""
        self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed handler '{handler.__name__}' to event '{event_type}'.")

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a registered handler."""
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)

    async def publish(self, event: AURAEvent, db: Optional[AsyncSession] = None) -> AURAEvent:
        """Persist event to transactional outbox and dispatch to active subscribers."""
        logger.info(
            f"EventBus publishing event '{event.event_type}' [{event.id}]",
            extra={"event_id": event.id, "event_type": event.event_type, "correlation_id": event.correlation_id},
        )

        db_record: Optional[EventRecordModel] = None

        if db is not None:
            db_record = EventRecordModel(
                id=event.id,
                event_type=event.event_type,
                source=event.source,
                payload_json=event.payload,
                status=EventStatus.PROCESSING.value,
                occurred_at=event.occurred_at,
                correlation_id=event.correlation_id,
            )
            db.add(db_record)
            await db.flush()

        # Find matching handlers (exact match + wildcard)
        matched_handlers = list(self._handlers.get(event.event_type, [])) + list(self._handlers.get("*", []))

        dispatch_error: Optional[Exception] = None

        for handler in matched_handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Error in event handler '{handler.__name__}' for event '{event.event_type}': {e}",
                    exc_info=True,
                    extra={"event_id": event.id, "event_type": event.event_type},
                )
                dispatch_error = e

        if db is not None and db_record is not None:
            if dispatch_error:
                db_record.status = EventStatus.FAILED.value
                db_record.retry_count += 1
                db_record.error_message = str(dispatch_error)
                event.status = EventStatus.FAILED
            else:
                db_record.status = EventStatus.PROCESSED.value
                db_record.processed_at = utc_now()
                event.status = EventStatus.PROCESSED
            await db.commit()
            await db.refresh(db_record)

        return event


# Global event bus singleton
event_bus = EventBus()
