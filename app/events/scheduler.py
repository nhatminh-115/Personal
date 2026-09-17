"""Persistent scheduler managing durable one-shot timers and recurring jobs."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import JobType, ScheduledJobModel, utc_now
from app.events.bus import EventBus, event_bus
from app.events.types import AURAEvent, EventType


class PersistentScheduler:
    """
    Persistent timer and cron scheduler backed by database tables:
    - One-shot timers survive server restarts and execute once due.
    - Recurring jobs compute next_run_at deterministically.
    - Emits structured AURAEvent messages to the EventBus.
    - Uses atomic leasing to prevent concurrent double-firing.
    """

    def __init__(self, bus: Optional[EventBus] = None) -> None:
        self.bus = bus or event_bus

    async def schedule_one_shot(
        self,
        name: str,
        delay_seconds: float,
        payload: Dict[str, Any],
        db: AsyncSession,
        run_at: Optional[datetime] = None,
    ) -> ScheduledJobModel:
        """Schedule a durable one-shot timer to execute at or after the target time."""
        target_time = run_at if run_at is not None else (utc_now() + timedelta(seconds=delay_seconds))

        job = ScheduledJobModel(
            name=name,
            job_type=JobType.ONE_SHOT.value,
            schedule_expression=str(delay_seconds),
            payload_json=payload,
            is_active=True,
            next_run_at=target_time,
            metadata_json={},
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        logger.info(
            f"Scheduled one-shot job '{job.id}' ({name}) for {target_time.isoformat()}",
            extra={"job_id": job.id, "next_run_at": target_time.isoformat()},
        )
        return job

    async def schedule_recurring(
        self,
        name: str,
        interval_seconds: float,
        payload: Dict[str, Any],
        db: AsyncSession,
    ) -> ScheduledJobModel:
        """Schedule a recurring job with a fixed interval in seconds."""
        target_time = utc_now() + timedelta(seconds=interval_seconds)

        job = ScheduledJobModel(
            name=name,
            job_type=JobType.RECURRING.value,
            schedule_expression=str(interval_seconds),
            payload_json=payload,
            is_active=True,
            next_run_at=target_time,
            metadata_json={},
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        logger.info(
            f"Scheduled recurring job '{job.id}' ({name}) every {interval_seconds}s",
            extra={"job_id": job.id, "interval": interval_seconds},
        )
        return job

    async def cancel_job(self, job_id: str, db: AsyncSession) -> bool:
        """Deactivate a scheduled job."""
        job = await db.get(ScheduledJobModel, job_id)
        if job and job.is_active:
            job.is_active = False
            await db.commit()
            logger.info(f"Cancelled scheduled job '{job_id}'", extra={"job_id": job_id})
            return True
        return False

    async def get_active_jobs(self, db: AsyncSession) -> List[ScheduledJobModel]:
        """Query all currently active scheduled jobs."""
        query = select(ScheduledJobModel).where(ScheduledJobModel.is_active.is_(True))
        result = await db.execute(query)
        return list(result.scalars().all())

    async def tick(
        self,
        db: AsyncSession,
        worker_id: Optional[str] = None,
        dispatch_immediate: bool = True,
    ) -> List[AURAEvent]:
        """
        Evaluate due jobs with concurrency-safe atomic leasing,
        emit corresponding events with idempotency keys, and update database states atomically.
        """
        import uuid
        worker_tag = worker_id or f"sched-{uuid.uuid4().hex[:6]}"
        now = utc_now()
        stale_lock_cutoff = now - timedelta(seconds=60)

        query = select(ScheduledJobModel).where(
            and_(
                ScheduledJobModel.is_active.is_(True),
                ScheduledJobModel.next_run_at <= now,
                or_(
                    ScheduledJobModel.locked_at.is_(None),
                    ScheduledJobModel.locked_at < stale_lock_cutoff,
                ),
            )
        )
        result = await db.execute(query)
        candidates = list(result.scalars().all())

        emitted_events: List[AURAEvent] = []

        for candidate in candidates:
            # Attempt atomic claim on this job
            claim_stmt = (
                update(ScheduledJobModel)
                .where(
                    and_(
                        ScheduledJobModel.id == candidate.id,
                        ScheduledJobModel.is_active.is_(True),
                        ScheduledJobModel.next_run_at <= now,
                        or_(
                            ScheduledJobModel.locked_at.is_(None),
                            ScheduledJobModel.locked_at < stale_lock_cutoff,
                        ),
                    )
                )
                .values(locked_at=now, locked_by=worker_tag)
                .execution_options(synchronize_session=False)
            )
            claim_res = await db.execute(claim_stmt)
            await db.commit()

            if claim_res.rowcount == 0:
                # Concurrent worker already claimed this job; skip to prevent duplicate trigger
                continue

            job = await db.get(ScheduledJobModel, candidate.id)
            if not job:
                continue

            evt_type = EventType.TIMER_FIRED.value if job.job_type == JobType.ONE_SHOT.value else EventType.CRON_TICK.value
            idemp_key = f"job-{job.id}-{int(job.next_run_at.timestamp())}"

            event = AURAEvent(
                event_type=evt_type,
                source="scheduler",
                payload=job.payload_json,
                correlation_id=job.id,
                idempotency_key=idemp_key,
            )

            published = await self.bus.publish(event, db=db, dispatch_immediate=dispatch_immediate)
            emitted_events.append(published)

            job.last_run_at = now
            job.locked_at = None
            job.locked_by = None

            if job.job_type == JobType.ONE_SHOT.value:
                job.is_active = False
            else:
                try:
                    interval = float(job.schedule_expression)
                    job.next_run_at = now + timedelta(seconds=interval)
                except ValueError:
                    job.next_run_at = now + timedelta(seconds=60.0)

            await db.commit()
            await db.refresh(job)

        return emitted_events


# Global scheduler singleton
persistent_scheduler = PersistentScheduler()
