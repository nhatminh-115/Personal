"""Tests for safe startup and shutdown lifecycle diagnostics."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.api import server
from app.api import run_recovery
from app.core.settings import settings
from app.events import runtime as event_runtime
from app.mcp import loader as mcp_loader
from app.mcp.manager import mcp_manager
from app.models.discovery import model_discovery_service


@pytest.mark.asyncio
async def test_lifecycle_logs_do_not_expose_startup_or_shutdown_exception_details(monkeypatch):
    model_secret = "model discovery URL token=private-model-token"
    mcp_secret = "MCP config secret=private-mcp-token"
    shutdown_secret = "shutdown endpoint https://private.example/?key=private-shutdown-token"
    warning_log = Mock()

    async def wait_for_recovery_shutdown():
        await asyncio.Event().wait()

    async def fail_loading_mcp_config(_path):
        raise RuntimeError(mcp_secret)

    monkeypatch.setattr(server, "init_db", AsyncMock())
    monkeypatch.setattr(server, "init_checkpointer", AsyncMock())
    monkeypatch.setattr(server, "close_checkpointer", AsyncMock())
    monkeypatch.setattr(run_recovery, "run_root_recovery_loop", wait_for_recovery_shutdown)
    monkeypatch.setattr(run_recovery, "recover_running_root_runs", AsyncMock(return_value={}))
    monkeypatch.setattr(
        model_discovery_service,
        "register_discovered_providers",
        AsyncMock(side_effect=RuntimeError(model_secret)),
    )
    monkeypatch.setattr(settings, "MCP_CONFIG_PATH", Path("unused-mcp-config.json"))
    monkeypatch.setattr(mcp_loader, "load_mcp_servers_from_file", fail_loading_mcp_config)
    monkeypatch.setattr(
        event_runtime,
        "start_automation_runtime",
        AsyncMock(return_value=AsyncMock()),
    )
    monkeypatch.setattr(
        mcp_manager,
        "disconnect_all",
        AsyncMock(side_effect=RuntimeError(shutdown_secret)),
    )
    monkeypatch.setattr(server.logger, "warning", warning_log)

    async with server.lifespan(server.create_app()):
        pass

    assert warning_log.call_args_list == [
        call("Non-fatal error during model discovery (error type: %s).", "RuntimeError"),
        call(
            "Non-fatal error during startup MCP tool loading/discovery (error type: %s).",
            "RuntimeError",
        ),
        call("Error disconnecting MCP servers on shutdown (error type: %s).", "RuntimeError"),
    ]
    logged_content = repr(warning_log.call_args_list)
    assert model_secret not in logged_content
    assert mcp_secret not in logged_content
    assert shutdown_secret not in logged_content
