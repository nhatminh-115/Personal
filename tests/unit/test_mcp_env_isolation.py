"""Unit tests verifying subprocess environment variable isolation and secret protection in MCP."""

import os
import sys
import pytest

from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_mcp_subprocess_secret_isolation():
    """
    Verify that ambient environment variables / credentials in host os.environ
    are NOT inherited by default into MCP subprocesses, preventing accidental credential exfiltration.
    """
    secret_key = "AURA_SUPER_SECRET_TOKEN"
    secret_value = "shhh-super-secret-credentials-987"
    os.environ[secret_key] = secret_value

    try:
        registry = ToolRegistry()
        manager = MCPClientManager(registry=registry)

        # 1. Server WITHOUT explicit env pass-through
        server_isolated = MCPServerConfig(
            id="isolated-server",
            name="Isolated MCP Server",
            transport=MCPTransportType.STDIO,
            command=sys.executable,
            args=["tests/fixtures/sample_mcp_server.py"],
            timeout_seconds=10.0,
        )
        manager.register_server(server_isolated)
        await manager.discover_tools("isolated-server")

        res_isolated = await manager.call_tool(
            server_id="isolated-server",
            tool_name="inspect_env",
            arguments={"var_name": secret_key},
        )
        assert res_isolated.success is True
        assert secret_value not in res_isolated.output
        assert "__NOT_SET__" in res_isolated.output

        # 2. Server WITH explicit env pass-through
        server_explicit = MCPServerConfig(
            id="explicit-server",
            name="Explicit MCP Server",
            transport=MCPTransportType.STDIO,
            command=sys.executable,
            args=["tests/fixtures/sample_mcp_server.py"],
            env={secret_key: "explicitly-authorized-value"},
            timeout_seconds=10.0,
        )
        manager.register_server(server_explicit)
        await manager.discover_tools("explicit-server")

        res_explicit = await manager.call_tool(
            server_id="explicit-server",
            tool_name="inspect_env",
            arguments={"var_name": secret_key},
        )
        assert res_explicit.success is True
        assert "explicitly-authorized-value" in res_explicit.output

    finally:
        os.environ.pop(secret_key, None)
        await manager.disconnect_all()
