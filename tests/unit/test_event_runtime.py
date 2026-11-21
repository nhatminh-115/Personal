"""Tests for failure isolation in the automation runtime loops."""

import asyncio
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.events import runtime


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_loop", ["scheduler", "outbox"])
async def test_runtime_loop_errors_do_not_log_exception_text(monkeypatch, failing_loop):
    private_diagnostic = "private event payload token=runtime-secret"
    log_recorded = asyncio.Event()
    error_log = Mock()

    def capture_error(*args, **kwargs):
        error_log(*args, **kwargs)
        log_recorded.set()

    scheduler_tick = AsyncMock(return_value=[])
    outbox_worker = Mock()
    outbox_worker.process_outbox_batch = AsyncMock(return_value=0)

    if failing_loop == "scheduler":
        scheduler_tick.side_effect = RuntimeError(private_diagnostic)
    else:
        outbox_worker.process_outbox_batch.side_effect = RuntimeError(private_diagnostic)

    monkeypatch.setattr(runtime, "POLL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(runtime, "async_session_factory", _SessionContext)
    monkeypatch.setattr(runtime.persistent_scheduler, "tick", scheduler_tick)
    monkeypatch.setattr(runtime, "OutboxWorker", Mock(return_value=outbox_worker))
    monkeypatch.setattr(runtime.logger, "error", capture_error)

    stop = await runtime.start_automation_runtime()
    try:
        await asyncio.wait_for(log_recorded.wait(), timeout=1)
    finally:
        await stop()

    expected_message = (
        "Persistent scheduler tick failed (error type: %s)."
        if failing_loop == "scheduler"
        else "Automation outbox processing failed (error type: %s)."
    )
    assert error_log.call_args_list == [call(expected_message, "RuntimeError")]
    assert private_diagnostic not in repr(error_log.call_args_list)
