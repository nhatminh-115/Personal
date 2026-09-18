"""Integration test verifying persistent MCP server configuration loading and lifecycle."""

import json
import os
import sys
import tempfile
from pathlib import Path
import pytest

from app.api.server import create_app, lifespan
from app.core.settings import settings
from app.mcp.manager import mcp_manager
from app.tools.registry import tool_registry


@pytest.mark.asyncio
async def test_mcp_config_startup_loading_and_lifecycle():
    """Prove that MCP tools appear automatically on app startup from config without manual register_server."""
    # 1. Prepare environment with explicit secret
    test_secret = "secret-token-xyz-987"
    os.environ["TEST_MCP_ENV_KEY"] = test_secret

    # 2. Write temporary mcp_servers.json referencing ${TEST_MCP_ENV_KEY}
    server_config_data = {
        "servers": [
            {
                "id": "auto-config-server",
                "name": "Auto Configured Server",
                "transport": "stdio",
                "command": sys.executable,
                "args": ["tests/fixtures/sample_mcp_server.py"],
                "env": {
                    "RESOLVED_SECRET": "${TEST_MCP_ENV_KEY}",
                },
                "auto_approve_tools": ["read_metric"],
                "timeout_seconds": 15.0,
                "enabled": True,
            }
        ]
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(server_config_data, f)
        config_path = f.name

    original_config_path = settings.MCP_CONFIG_PATH
    settings.MCP_CONFIG_PATH = Path(config_path)

    try:
        app = create_app()

        # Before lifespan: tool should not exist in tool_registry
        assert tool_registry.get("mcp_auto-config-server_read_metric") is None

        # Execute application lifespan
        async with lifespan(app):
            # Assert server was registered in mcp_manager
            srv = mcp_manager.get_server_config("auto-config-server")
            assert srv is not None
            assert srv.name == "Auto Configured Server"
            # Verify secret indirection was resolved
            assert srv.env.get("RESOLVED_SECRET") == test_secret

            # Assert tools were discovered and registered into the SAME tool_registry used by orchestrator
            tool = tool_registry.get("mcp_auto-config-server_read_metric")
            assert tool is not None, "Expected mcp_auto-config-server_read_metric in tool_registry!"
            assert "sample-mcp" not in tool.name

            # Test executing discovered tool
            res = await tool.execute({"metric_name": "cpu_usage"})
            assert res.success is True
            assert "cpu_usage" in res.output

        # After shutdown: tools should be unregistered from mcp_manager and tool_registry
        assert mcp_manager.get_server_config("auto-config-server") is None
        assert tool_registry.get("mcp_auto-config-server_read_metric") is None

    finally:
        settings.MCP_CONFIG_PATH = original_config_path
        os.environ.pop("TEST_MCP_ENV_KEY", None)
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_mcp_config_missing_required_secret_fails_loudly():
    """Prove that an unresolvable ${VAR} without default raises ValueError and does not leak host env."""
    os.environ.pop("NON_EXISTENT_SECRET_XYZ", None)

    server_config_data = {
        "servers": [
            {
                "id": "failing-server",
                "name": "Failing Server",
                "transport": "stdio",
                "command": "python",
                "env": {
                    "API_KEY": "${NON_EXISTENT_SECRET_XYZ}",
                },
            }
        ]
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(server_config_data, f)
        config_path = f.name

    try:
        from app.mcp.loader import load_mcp_servers_from_file

        with pytest.raises(ValueError) as exc_info:
            load_mcp_servers_from_file(config_path)

        assert "NON_EXISTENT_SECRET_XYZ" in str(exc_info.value)
    finally:
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
            except OSError:
                pass
