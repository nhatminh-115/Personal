"""Tests for safe outbox lease heartbeat diagnostics."""

import asyncio
from unittest.mock import Mock, call

import pytest

from app.events import worker as worker_module
from app.events.worker import OutboxWorker


class _LeaseSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("UPDATE event_records secret=private-lease-diagnostic")


@pytest.mark.asyncio
async def test_lease_heartbeat_failure_logs_category_without_database_diagnostics(monkeypatch):
    log_recorded = asyncio.Event()
    error_log = Mock()

    def capture_error(*args, **kwargs):
        error_log(*args, **kwargs)
        log_recorded.set()

    monkeypatch.setattr(
        worker_module,
        "async_sessionmaker",
        lambda _bind, **_kwargs: _LeaseSession,
    )
    monkeypatch.setattr(worker_module.logger, "error", capture_error)

    worker = OutboxWorker(worker_id="lease-test", lease_duration_seconds=1)
    stopped = asyncio.Event()
    heartbeat = asyncio.create_task(worker._renew_batch_leases(object(), ["event-1"], stopped))
    try:
        await asyncio.wait_for(log_recorded.wait(), timeout=2)
    finally:
        stopped.set()
        await heartbeat

    assert error_log.call_args_list == [
        call(
            "Failed to renew outbox worker lease (error type: %s).",
            "RuntimeError",
            extra={"worker_id": "lease-test"},
        )
    ]
    assert "private-lease-diagnostic" not in repr(error_log.call_args_list)
