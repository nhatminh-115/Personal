"""Background loop for durable scheduled AURA automations."""

import asyncio
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.session import async_session_factory
from app.events.bus import EventBus, event_bus
from app.events.dispatcher import EventToAgentBridge
from app.events.scheduler import PersistentScheduler, persistent_scheduler
from app.events.types import EventType
from app.events.worker import OutboxWorker


async def run_automation_runtime(
    stop_event: asyncio.Event,
    *,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
    bus: EventBus = event_bus,
    scheduler: PersistentScheduler = persistent_scheduler,
    outbox_worker: OutboxWorker | None = None,
    poll_interval_seconds: float = 1.0,
) -> None:
    """Tick durable schedules and deliver outbox events until shutdown."""
    bridge = EventToAgentBridge(session_factory)
    event_types = (
        EventType.TIMER_FIRED.value,
        EventType.CRON_TICK.value,
        EventType.TASK_RESUMED.value,
    )
    for event_type in event_types:
        bus.subscribe(event_type, bridge.handle_event)

    worker = outbox_worker or OutboxWorker(bus=bus)
    try:
        while not stop_event.is_set():
            try:
                async with session_factory() as db:
                    await scheduler.tick(db, dispatch_immediate=False)

                async with session_factory() as db:
                    await worker.process_outbox_batch(db, batch_size=20)
            except Exception:
                logger.exception("Automation scheduler/outbox cycle failed; retrying on the next tick")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
            except asyncio.TimeoutError:
                pass
    finally:
        for event_type in event_types:
            bus.unsubscribe(event_type, bridge.handle_event)
