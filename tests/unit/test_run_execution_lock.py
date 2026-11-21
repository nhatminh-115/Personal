"""Process-local coordination for cancellation recovery."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.run_resume_lock import (
    lock_run_execution,
    lock_run_resume,
    try_lock_run_execution,
    try_lock_run_resume,
)


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
