import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from app.mcp.adapter import MCPToolAdapter
from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.mcp.policy import MCPSecurityPolicy
from app.tools.base import RiskLevel


@pytest.mark.asyncio
async def test_mcp_tool_call_failure_does_not_return_or_log_transport_diagnostic(monkeypatch, caplog):
    diagnostic = "private MCP endpoint token=secret-value"
    manager = MCPClientManager()
    manager.register_server(
        MCPServerConfig(id="remote", name="Remote", transport=MCPTransportType.STDIO, command="unused")
    )

    @asynccontextmanager
    async def failing_stdio_client(_params):
        raise RuntimeError(diagnostic)
        yield None

    monkeypatch.setattr("app.mcp.manager.stdio_client", failing_stdio_client)

    with caplog.at_level(logging.ERROR, logger="aura"):
        result = await manager.call_tool("remote", "lookup", {})

    assert result.success is False
    assert result.error == "MCP server operation failed."
    assert result.metadata["error_category"] == "mcp_server_error"
    assert diagnostic not in result.error
    assert diagnostic not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.asyncio
async def test_mcp_discovery_failure_does_not_log_transport_diagnostic(monkeypatch, caplog):
    diagnostic = "private MCP discovery response"
    manager = MCPClientManager()
    manager.register_server(
        MCPServerConfig(id="remote", name="Remote", transport=MCPTransportType.STDIO, command="unused")
    )

    @asynccontextmanager
    async def failing_stdio_client(_params):
        raise RuntimeError(diagnostic)
        yield None

    monkeypatch.setattr("app.mcp.manager.stdio_client", failing_stdio_client)

    with caplog.at_level(logging.ERROR, logger="aura"):
        assert await manager.discover_tools("remote") == []

    assert diagnostic not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.asyncio
async def test_mcp_adapter_failure_does_not_return_or_log_manager_diagnostic(caplog):
    diagnostic = "private MCP manager failure"
    manager = MagicMock()
    manager.call_tool = AsyncMock(side_effect=RuntimeError(diagnostic))
    adapter = MCPToolAdapter(
        server_id="remote",
        mcp_tool_name="lookup",
        description="Lookup data",
        input_schema={},
        risk_level=RiskLevel.HIGH,
        required_capabilities=[],
        manager=manager,
        policy=MCPSecurityPolicy(),
    )

    with caplog.at_level(logging.ERROR, logger="aura"):
        result = await adapter.execute({})

    assert result.success is False
    assert result.error == "MCP tool invocation failed."
    assert result.metadata["error_category"] == "mcp_execution_failure"
    assert diagnostic not in result.error
    assert diagnostic not in caplog.text
    assert "Traceback" not in caplog.text


@pytest.mark.asyncio
async def test_mcp_schema_validation_does_not_echo_sensitive_argument(caplog):
    secret_value = "private-value-that-must-not-appear"
    adapter = MCPToolAdapter(
        server_id="remote",
        mcp_tool_name="lookup",
        description="Lookup data",
        input_schema={"type": "object", "properties": {"limit": {"type": "integer"}}},
        risk_level=RiskLevel.HIGH,
        required_capabilities=[],
        manager=MagicMock(),
        policy=MCPSecurityPolicy(),
    )

    with caplog.at_level(logging.WARNING, logger="aura"):
        result = await adapter.execute({"limit": secret_value})

    assert result.success is False
    assert "Schema validation failed" in result.error
    assert result.metadata["error_category"] == "validation_error"
    assert secret_value not in result.error
    assert secret_value not in caplog.text


def test_mcp_config_parser_diagnostic_is_not_logged(tmp_path, caplog):
    from app.mcp.loader import load_mcp_servers_from_file

    secret_value = "private-config-value"
    path = tmp_path / "servers.yaml"
    path.write_text(f"servers: [\n  token: {secret_value}\n", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="aura"):
        with pytest.raises(yaml.YAMLError):
            load_mcp_servers_from_file(path)

    assert "Failed to load MCP server configuration." in caplog.text
    assert secret_value not in caplog.text
    assert "Traceback" not in caplog.text
