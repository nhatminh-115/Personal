"""Serialize durable run resumes across API workers."""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


_run_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _get_process_lock(run_id: str) -> asyncio.Lock:
    async with _locks_guard:
        return _run_locks.setdefault(run_id, asyncio.Lock())


@asynccontextmanager
async def _postgres_run_resume_lock(engine: AsyncEngine, run_id: str) -> AsyncIterator[None]:
    """Hold a session advisory lock until the resumed graph has finished."""
    lock_params = {"run_id": run_id}
    acquire = text("SELECT pg_advisory_lock(hashtext('aura:run-resume'), hashtext(:run_id))")
    release = text("SELECT pg_advisory_unlock(hashtext('aura:run-resume'), hashtext(:run_id))")

    async with engine.connect() as connection:
        acquired = False
        try:
            try:
                await connection.execute(acquire, lock_params)
            except BaseException:
                # The server may have acquired the lock even if the client
                # lost the acknowledgement. Do not return that connection to
                # the pool in an ambiguous state.
                await connection.invalidate()
                raise
            acquired = True
            # Session-level advisory locks survive transaction boundaries.
            await connection.commit()
            yield
        finally:
            if acquired:
                try:
                    await connection.execute(release, lock_params)
                    await connection.commit()
                except BaseException:
                    # Never return a pooled connection that may still own the
                    # advisory lock; closing it releases the PostgreSQL lock.
                    await connection.invalidate()
                    raise


@asynccontextmanager
async def _postgres_run_execution_lock(engine: AsyncEngine, run_id: str) -> AsyncIterator[None]:
    """Hold an advisory lock while a root chat graph is actively executing."""
    lock_params = {"run_id": run_id}
    acquire = text("SELECT pg_advisory_lock(hashtext('aura:run-execution'), hashtext(:run_id))")
    release = text("SELECT pg_advisory_unlock(hashtext('aura:run-execution'), hashtext(:run_id))")

    async with engine.connect() as connection:
        acquired = False
        try:
            try:
                await connection.execute(acquire, lock_params)
            except BaseException:
                await connection.invalidate()
                raise
            acquired = True
            await connection.commit()
            yield
        finally:
            if acquired:
                try:
                    await connection.execute(release, lock_params)
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise


@asynccontextmanager
async def lock_run_resume(db: AsyncSession, run_id: str) -> AsyncIterator[None]:
    """Serialize one run's resume locally and, on PostgreSQL, across workers.

    SQLite uses the process lock because it has no advisory locks and the
    supported local deployment runs a single API process. PostgreSQL's
    session lock remains held while graph execution commits its own work.
    """
    process_lock = await _get_process_lock(run_id)
    async with process_lock:
        if db.get_bind().dialect.name == "postgresql":
            bind = db.bind
            if not isinstance(bind, AsyncEngine):
                raise RuntimeError("Run resume coordination requires an async PostgreSQL engine.")
            async with _postgres_run_resume_lock(bind, run_id):
                yield
        else:
            yield


@asynccontextmanager
async def lock_run_execution(db: AsyncSession, run_id: str) -> AsyncIterator[None]:
    """Serialize initial/resumed chat graph execution against crash recovery."""
    process_lock = await _get_process_lock(f"execution:{run_id}")
    async with process_lock:
        if db.get_bind().dialect.name == "postgresql":
            bind = db.bind
            if not isinstance(bind, AsyncEngine):
                raise RuntimeError("Run execution coordination requires an async PostgreSQL engine.")
            async with _postgres_run_execution_lock(bind, run_id):
                yield
        else:
            yield


@asynccontextmanager
async def try_lock_run_execution(db: AsyncSession, run_id: str) -> AsyncIterator[bool]:
    """Try to claim an execution thread for cancellation recovery without waiting."""
    process_lock = await _get_process_lock(f"execution:{run_id}")
    if db.get_bind().dialect.name == "postgresql":
        bind = db.bind
        if not isinstance(bind, AsyncEngine):
            raise RuntimeError("Run execution coordination requires an async PostgreSQL engine.")

        lock_params = {"run_id": run_id}
        acquire = text("SELECT pg_try_advisory_lock(hashtext('aura:run-execution'), hashtext(:run_id))")
        release = text("SELECT pg_advisory_unlock(hashtext('aura:run-execution'), hashtext(:run_id))")
        async with bind.connect() as connection:
            acquired = False
            try:
                try:
                    result = await connection.execute(acquire, lock_params)
                    acquired = bool(result.scalar_one())
                    await connection.commit()
                except BaseException:
                    await connection.invalidate()
                    raise
                yield acquired
            finally:
                if acquired:
                    try:
                        await connection.execute(release, lock_params)
                        await connection.commit()
                    except BaseException:
                        await connection.invalidate()
                        raise
        return

    if process_lock.locked():
        yield False
        return

    await process_lock.acquire()
    try:
        yield True
    finally:
        process_lock.release()
