"""Application lifecycle for durable scheduler and outbox processing."""

import asyncio
from collections.abc import Awaitable, Callable

from app.core.logging import logger
from app.db.session import async_session_factory
from app.events.bus import event_bus
from app.events.dispatcher import EventToAgentBridge
from app.events.scheduler import persistent_scheduler
from app.events.types import EventType
from app.events.worker import OutboxWorker

POLL_INTERVAL_SECONDS = 1.0


async def start_automation_runtime() -> Callable[[], Awaitable[None]]:
    """Start the durable scheduler/outbox loops and return their shutdown hook."""
    bridge = EventToAgentBridge()
    event_bus.subscribe(EventType.TIMER_FIRED.value, bridge.handle_event)
    event_bus.subscribe(EventType.CRON_TICK.value, bridge.handle_event)
    event_bus.subscribe(EventType.WEBHOOK_RECEIVED.value, bridge.handle_event)
    worker = OutboxWorker()
    stopped = asyncio.Event()

    async def scheduler_loop() -> None:
        while not stopped.is_set():
            try:
                async with async_session_factory() as db:
                    await persistent_scheduler.tick(db, dispatch_immediate=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Persistent scheduler tick failed")
            try:
                await asyncio.wait_for(stopped.wait(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                pass

    async def outbox_loop() -> None:
        while not stopped.is_set():
            try:
                async with async_session_factory() as db:
                    processed = await worker.process_outbox_batch(db)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Automation outbox processing failed")
                processed = 0
            if processed == 0:
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=POLL_INTERVAL_SECONDS)
                except TimeoutError:
                    pass

    tasks = [
        asyncio.create_task(scheduler_loop(), name="aura-scheduler"),
        asyncio.create_task(outbox_loop(), name="aura-automation-outbox"),
    ]

    async def stop() -> None:
        stopped.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event_bus.unsubscribe(EventType.TIMER_FIRED.value, bridge.handle_event)
        event_bus.unsubscribe(EventType.CRON_TICK.value, bridge.handle_event)
        event_bus.unsubscribe(EventType.WEBHOOK_RECEIVED.value, bridge.handle_event)

    return stop
