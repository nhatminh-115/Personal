"""Integration test proving database-enforced, race-safe Outbox idempotency under concurrency."""

import asyncio
import os
import tempfile
import uuid
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import EventRecordModel
from app.events.bus import EventBus
from app.events.types import AURAEvent, EventType


@pytest.fixture
def concurrency_db_engine():
    """Create a temporary SQLite database with current schema for concurrency testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    async_url = f"sqlite+aiosqlite:///{db_path.replace(chr(92), '/')}"
    engine = create_async_engine(async_url, echo=False)

    yield engine, db_path

    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_concurrent_idempotent_event_publishing(concurrency_db_engine):
    """Prove that concurrent producers publishing the same idempotency_key result in exactly one DB row."""
    engine, db_path = concurrency_db_engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    bus = EventBus()
    shared_key = f"race-idemp-{uuid.uuid4().hex[:8]}"

    num_concurrent_producers = 10

    async def publish_producer(index: int):
        async with session_maker() as session:
            evt = AURAEvent(
                event_type=EventType.TIMER_FIRED.value,
                payload={"index": index, "data": "concurrent_payload"},
                source=f"producer_{index}",
                correlation_id=f"corr-{index}",
                idempotency_key=shared_key,
            )
            # Concurrent producers call publish simultaneously
            published = await bus.publish(evt, db=session)
            return published

    # Launch all concurrent tasks simultaneously
    tasks = [publish_producer(i) for i in range(num_concurrent_producers)]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # 1. Assert all returned results succeeded and have valid IDs
    assert len(results) == num_concurrent_producers
    winning_id = results[0].id
    assert winning_id is not None

    # 2. Assert every concurrent producer resolved to the winning event ID
    for res in results:
        assert res.id == winning_id, f"Producer got different ID: {res.id} vs winning {winning_id}"
        assert res.idempotency_key == shared_key

    # 3. Assert exactly one row exists in the database
    async with session_maker() as session:
        stmt = select(func.count(EventRecordModel.id)).where(
            EventRecordModel.idempotency_key == shared_key
        )
        count = await session.scalar(stmt)
        assert count == 1, f"Expected exactly 1 database row, but found {count}!"

        # Check the row itself
        row = (
            await session.execute(
                select(EventRecordModel).where(EventRecordModel.idempotency_key == shared_key)
            )
        ).scalar_one()
        assert row.id == winning_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_null_idempotency_keys_allow_multiple_events(concurrency_db_engine):
    """Prove that null idempotency_key allows multiple distinct events without constraint violation."""
    engine, db_path = concurrency_db_engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    bus = EventBus()

    async with session_maker() as s1, session_maker() as s2:
        evt1 = AURAEvent(
            event_type=EventType.TIMER_FIRED.value,
            payload={"test": 1},
            source="test",
            idempotency_key=None,
        )
        evt2 = AURAEvent(
            event_type=EventType.TIMER_FIRED.value,
            payload={"test": 2},
            source="test",
            idempotency_key=None,
        )

        p1 = await bus.publish(evt1, db=s1)
        p2 = await bus.publish(evt2, db=s2)

        assert p1.id != p2.id

    await engine.dispose()
