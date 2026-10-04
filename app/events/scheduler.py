"""Persistent scheduler managing durable one-shot timers and recurring jobs."""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import logger
from app.db.models import EventRecordModel, EventStatus, JobType, RunModel, RunStatus, ScheduledJobModel, utc_now
from app.events.bus import EventBus, event_bus
from app.events.automation_schedule import AutomationSchedule, next_automation_run
from app.events.types import AURAEvent, EventType

MAX_DUE_JOBS_PER_TICK = 100


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

    async def _automation_has_active_execution(self, db: AsyncSession, job: ScheduledJobModel) -> bool:
        """Avoid overlapping unattended automation runs while a prior trigger is still active."""
        metadata = job.metadata_json if isinstance(job.metadata_json, dict) else {}
        if metadata.get("kind") != "automation":
            return False

        result = await db.execute(
            select(EventRecordModel)
            .where(
                EventRecordModel.correlation_id == job.id,
                EventRecordModel.event_type.in_({EventType.TIMER_FIRED.value, EventType.CRON_TICK.value}),
            )
            .order_by(EventRecordModel.occurred_at.desc(), EventRecordModel.id.desc())
            .limit(1)
        )
        event = result.scalar_one_or_none()
        if event is None or event.status in {EventStatus.DEAD_LETTER.value, EventStatus.PROCESSED.value}:
            if event is None or event.status == EventStatus.DEAD_LETTER.value:
                return False
        elif event.status in {
            EventStatus.PENDING.value,
            EventStatus.PROCESSING.value,
            EventStatus.FAILED.value,
        }:
            return True

        if event is None or event.status != EventStatus.PROCESSED.value:
            return False
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))
        run = await db.get(RunModel, run_id)
        return bool(run and run.status in {
            RunStatus.RUNNING.value,
            RunStatus.WAITING_FOR_APPROVAL.value,
            RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value,
        })

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
        ).order_by(ScheduledJobModel.next_run_at, ScheduledJobModel.id).limit(MAX_DUE_JOBS_PER_TICK)
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
            if job.job_type != JobType.ONE_SHOT.value and await self._automation_has_active_execution(db, job):
                try:
                    interval = float(job.schedule_expression)
                    metadata = job.metadata_json if isinstance(job.metadata_json, dict) else {}
                    if metadata.get("kind") == "automation":
                        schedule = AutomationSchedule.model_validate(metadata.get("schedule", {}))
                        job.next_run_at = next_automation_run(schedule, now, int(interval))
                    else:
                        job.next_run_at = now + timedelta(seconds=interval)
                except (TypeError, ValueError):
                    job.next_run_at = now + timedelta(seconds=60.0)
                job.locked_at = None
                job.locked_by = None
                # The bulk claim bypassed the identity map, so force both lease
                # fields into the UPDATE even if this ORM instance still says None.
                flag_modified(job, "locked_at")
                flag_modified(job, "locked_by")
                await db.commit()
                await db.refresh(job)
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
            flag_modified(job, "locked_at")
            flag_modified(job, "locked_by")

            if job.job_type == JobType.ONE_SHOT.value:
                job.is_active = False
            else:
                try:
                    interval = float(job.schedule_expression)
                    metadata = job.metadata_json if isinstance(job.metadata_json, dict) else {}
                    if metadata.get("kind") == "automation":
                        schedule = AutomationSchedule.model_validate(metadata.get("schedule", {}))
                        job.next_run_at = next_automation_run(schedule, now, int(interval))
                    else:
                        job.next_run_at = now + timedelta(seconds=interval)
                except ValueError:
                    job.next_run_at = now + timedelta(seconds=60.0)

            await db.commit()
            await db.refresh(job)

        return emitted_events


# Global scheduler singleton
persistent_scheduler = PersistentScheduler()
