"""Keep unexpected delegation failures out of tool results and logs."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.errors import ProviderError, ToolError
from app.tools.delegation import DelegateTaskTool


@pytest.mark.asyncio
async def test_delegate_task_tool_redacts_unexpected_runtime_failure(monkeypatch):
    diagnostic = "private endpoint https://svc.internal/?token=secret"
    runtime = MagicMock()
    runtime.delegate = AsyncMock(side_effect=RuntimeError(diagnostic))
    log_error = MagicMock()
    monkeypatch.setattr("app.tools.delegation.logger.error", log_error)

    result = await DelegateTaskTool(runtime=runtime).execute(
        {"specialist_name": "coding", "task_description": "Inspect the workspace"},
        context={"db": object(), "run_id": "parent-run"},
    )

    assert result.success is False
    assert result.error == "Delegation failed because an internal error occurred."
    assert result.metadata == {
        "specialist_name": "coding",
        "error_category": "internal_error",
        "error_type": "RuntimeError",
    }
    assert diagnostic not in json.dumps(
        {"result": result.model_dump(), "logs": log_error.call_args_list},
        default=str,
    )


@pytest.mark.asyncio
async def test_delegate_task_tool_preserves_safe_preflight_rejection():
    runtime = MagicMock()
    runtime.delegate = AsyncMock(side_effect=ToolError("Specialist 'unknown' is not registered."))

    result = await DelegateTaskTool(runtime=runtime).execute(
        {"specialist_name": "unknown", "task_description": "Do a task"},
        context={"db": object()},
    )

    assert result.success is False
    assert result.error == "Specialist 'unknown' is not registered."
    assert result.metadata["error_category"] == "delegation_rejected"


@pytest.mark.asyncio
async def test_delegate_task_tool_uses_generic_provider_failure_message():
    diagnostic = "provider response included https://provider.invalid/?api_key=secret"
    runtime = MagicMock()
    runtime.delegate = AsyncMock(side_effect=ProviderError(diagnostic))

    result = await DelegateTaskTool(runtime=runtime).execute(
        {"specialist_name": "coding", "task_description": "Inspect the workspace"},
        context={"db": object()},
    )

    assert result.success is False
    assert result.error == (
        "The selected model provider could not complete this request. "
        "Check provider availability and routing settings, then retry."
    )
    assert result.metadata["error_category"] == "provider_failure"
    assert result.metadata["error_type"] == "ProviderError"
    assert diagnostic not in result.error

