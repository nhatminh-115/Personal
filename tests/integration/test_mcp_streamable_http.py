"""Integration test for MCP v2 Streamable HTTP transport and client session lifecycle."""

import asyncio
import socket
import pytest
import uvicorn

from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.tools.registry import ToolRegistry
from tests.fixtures.sample_mcp_http_server import create_app


def get_free_port() -> int:
    """Find a random free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def mcp_http_server():
    """Spin up local Streamable HTTP MCP server in background task."""
    port = get_free_port()
    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    # Wait for server startup
    for _ in range(30):
        await asyncio.sleep(0.1)
        if server.started:
            break

    url = f"http://127.0.0.1:{port}/mcp"
    yield url

    server.should_exit = True
    await server_task


@pytest.mark.asyncio
async def test_mcp_streamable_http_discovery_and_execution(mcp_http_server: str):
    """
    Verify complete MCP v2 Streamable HTTP workflow:
    - Register server with transport='streamable-http'
    - Discover tools over HTTP POST/GET streamable protocol
    - Call discovered tool successfully
    - Isolate tool execution failures cleanly
    """
    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)

    server_config = MCPServerConfig(
        id="http-test-server",
        name="Streamable HTTP Test Server",
        transport=MCPTransportType.STREAMABLE_HTTP,
        url=mcp_http_server,
        timeout_seconds=10.0,
    )
    manager.register_server(server_config)

    # 1. Discover tools over streamable-http
    tools = await manager.discover_tools("http-test-server")
    tool_names = [t.name for t in tools]
    assert "mcp_http-test-server_http_echo" in tool_names
    assert "mcp_http-test-server_http_add" in tool_names

    # 2. Call echo tool
    echo_result = await manager.call_tool(
        server_id="http-test-server",
        tool_name="http_echo",
        arguments={"message": "hello streamable http"},
    )
    assert echo_result.success is True
    assert "http-echo: hello streamable http" in echo_result.output

    # 3. Call add tool
    add_result = await manager.call_tool(
        server_id="http-test-server",
        tool_name="http_add",
        arguments={"a": 17, "b": 25},
    )
    assert add_result.success is True
    assert "42" in add_result.output

    # 4. Error isolation for failing tool
    fail_result = await manager.call_tool(
        server_id="http-test-server",
        tool_name="http_failing_tool",
        arguments={},
    )
    assert fail_result.success is False
    assert fail_result.error is not None
    assert "Error executing tool" in fail_result.error or "Simulated" in fail_result.error

    # Clean up
    await manager.disconnect_all()
