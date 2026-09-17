"""Transactional outbox background worker with atomic claiming, retry backoff, and dead-letter queues."""

import asyncio
from datetime import timedelta
from typing import List, Optional
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import EventRecordModel, EventStatus, utc_now
from app.events.bus import EventBus, event_bus
from app.events.types import AURAEvent


class OutboxWorker:
    """
    Consumer process for the Transactional Outbox pattern:
    - Atomically claims pending events with locked_at leasing to prevent double processing.
    - Dispatches events to subscribers.
    - Implements exponential backoff retries.
    - Dead-letters persistently failing events when max_attempts is exceeded.
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        worker_id: Optional[str] = None,
        lease_duration_seconds: int = 60,
    ) -> None:
        self.bus = bus or event_bus
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.lease_duration = timedelta(seconds=lease_duration_seconds)

    async def process_outbox_batch(self, db: AsyncSession, batch_size: int = 10) -> int:
        """Claim and process a single batch of pending outbox events."""
        now = utc_now()
        is_postgres = db.bind.dialect.name == "postgresql" if db.bind else False

        # Expired lock threshold for stale worker crash recovery
        stale_lock_cutoff = now - self.lease_duration

        # Query pending events that are due and not locked by an active worker
        claim_condition = and_(
            EventRecordModel.status.in_([EventStatus.PENDING.value, EventStatus.FAILED.value]),
            or_(
                EventRecordModel.next_attempt_at.is_(None),
                EventRecordModel.next_attempt_at <= now,
            ),
            or_(
                EventRecordModel.locked_at.is_(None),
                EventRecordModel.locked_at < stale_lock_cutoff,
            ),
        )

        query = (
            select(EventRecordModel)
            .where(claim_condition)
            .order_by(EventRecordModel.occurred_at.asc())
            .limit(batch_size)
        )

        if is_postgres:
            query = query.with_for_update(skip_locked=True)

        result = await db.execute(query)
        records: List[EventRecordModel] = list(result.scalars().all())

        if not records:
            return 0

        # Mark claimed
        for rec in records:
            rec.status = EventStatus.PROCESSING.value
            rec.locked_at = now
            rec.locked_by = self.worker_id

        await db.commit()

        processed_count = 0

        for rec in records:
            event = AURAEvent(
                id=rec.id,
                event_type=rec.event_type,
                source=rec.source,
                payload=rec.payload_json,
                occurred_at=rec.occurred_at,
                correlation_id=rec.correlation_id,
                idempotency_key=rec.idempotency_key,
                status=EventStatus(rec.status),
                retry_count=rec.retry_count,
                max_attempts=rec.max_attempts,
            )

            # Find matching handlers
            matched_handlers = list(self.bus._handlers.get(event.event_type, [])) + list(self.bus._handlers.get("*", []))
            handler_error: Optional[Exception] = None

            for handler in matched_handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        res = handler(event)
                        if asyncio.iscoroutine(res):
                            await res
                except Exception as e:
                    logger.error(
                        f"OutboxWorker handler error on event '{event.id}' ({event.event_type}): {e}",
                        exc_info=True,
                        extra={"event_id": event.id, "worker_id": self.worker_id},
                    )
                    handler_error = e
                    break

            # Reload record in active session
            active_rec = await db.get(EventRecordModel, rec.id)
            if not active_rec:
                continue

            active_rec.locked_at = None
            active_rec.locked_by = None

            if handler_error is None:
                active_rec.status = EventStatus.PROCESSED.value
                active_rec.processed_at = utc_now()
                active_rec.error_message = None
                processed_count += 1
            else:
                active_rec.retry_count += 1
                active_rec.error_message = str(handler_error)
                if active_rec.retry_count >= active_rec.max_attempts:
                    active_rec.status = EventStatus.DEAD_LETTER.value
                    logger.error(
                        f"Event '{active_rec.id}' moved to DEAD_LETTER after {active_rec.retry_count} attempts.",
                        extra={"event_id": active_rec.id},
                    )
                else:
                    active_rec.status = EventStatus.FAILED.value
                    backoff_seconds = min(300, 2 ** active_rec.retry_count)
                    active_rec.next_attempt_at = utc_now() + timedelta(seconds=backoff_seconds)

            await db.commit()

        return processed_count
