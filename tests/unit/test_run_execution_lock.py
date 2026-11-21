"""Process-local coordination for cancellation recovery."""

import gc
import uuid
import weakref

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.run_resume_lock import (
    lock_run_execution,
    lock_run_resume,
    try_lock_run_execution,
    try_lock_run_resume,
)
from app.api import run_resume_lock as run_locks


@pytest.mark.asyncio
async def test_execution_lock_try_acquire_is_nonblocking_and_released():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    run_id = str(uuid.uuid4())

    try:
        async with factory() as session:
            async with lock_run_execution(session, run_id):
                async with try_lock_run_execution(session, run_id) as acquired:
                    assert acquired is False

            async with try_lock_run_execution(session, run_id) as acquired:
                assert acquired is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resume_lock_try_acquire_is_nonblocking_and_released():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    run_id = str(uuid.uuid4())

    try:
        async with factory() as session:
            async with lock_run_resume(session, run_id):
                async with try_lock_run_resume(session, run_id) as acquired:
                    assert acquired is False

            async with try_lock_run_resume(session, run_id) as acquired:
                assert acquired is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_inactive_process_locks_are_not_retained_by_registry():
    run_id = str(uuid.uuid4())

    process_lock = await run_locks._get_process_lock(run_id)
    process_lock_ref = weakref.ref(process_lock)
    assert await run_locks._get_process_lock(run_id) is process_lock

    del process_lock
    gc.collect()

    assert process_lock_ref() is None
    assert run_locks._run_locks.get(run_id) is None
