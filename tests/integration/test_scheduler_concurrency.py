"""Integration test verifying concurrency-safe scheduler leasing and preventing double-firing."""

import asyncio
from datetime import timedelta
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ScheduledJobModel, utc_now
from app.events.bus import EventBus
from app.events.scheduler import PersistentScheduler


@pytest.mark.asyncio
async def test_scheduler_concurrency_lease_prevents_duplicate_fires(test_db_session: AsyncSession):
    """
    Simulate 5 concurrent scheduler worker processes ticking simultaneously on the same database.
    Verify that each due job is claimed by exactly one worker and emitted exactly once.
    """
    bus = EventBus()
    scheduler = PersistentScheduler(bus=bus)

    now = utc_now()
    due_time = now - timedelta(seconds=10)

    # 1. Create 3 due one-shot jobs
    jobs = []
    for i in range(3):
        job = ScheduledJobModel(
            name=f"concurrency-test-job-{i}",
            job_type="one_shot",
            schedule_expression="10",
            payload_json={"job_index": i},
            is_active=True,
            next_run_at=due_time,
            metadata_json={},
        )
        test_db_session.add(job)
        jobs.append(job)
    await test_db_session.commit()

    # Create session factory sharing the same engine
    engine = test_db_session.bind
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 2. Spawn 5 workers ticking simultaneously
    async def worker_tick_task(worker_index: int):
        async with session_factory() as session:
            return await scheduler.tick(db=session, worker_id=f"worker-{worker_index}")

    tasks = [worker_tick_task(w) for w in range(5)]
    results = await asyncio.gather(*tasks)

    # 3. Aggregate all emitted events across all workers
    all_emitted = []
    for worker_events in results:
        all_emitted.extend(worker_events)

    # Exactly 3 events should have been emitted (one per due job)
    assert len(all_emitted) == 3, f"Expected exactly 3 emitted events, got {len(all_emitted)}"

    # Ensure all job indices 0, 1, 2 were covered with no duplicates
    emitted_indices = sorted([e.payload["job_index"] for e in all_emitted])
    assert emitted_indices == [0, 1, 2]

    # Verify all jobs are now inactive
    job_ids = [j.id for j in jobs]
    async with session_factory() as verify_session:
        for jid in job_ids:
            reloaded = await verify_session.get(ScheduledJobModel, jid)
            assert reloaded is not None
            assert reloaded.is_active is False
