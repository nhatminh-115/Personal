"""Integration test for authenticated MCP v2 Streamable HTTP transport."""

import asyncio
import socket
import pytest
import uvicorn
from starlette.responses import PlainTextResponse

from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.tools.registry import ToolRegistry
from tests.fixtures.sample_mcp_http_server import create_app as create_base_app


class AuthCheckMiddleware:
    """Middleware enforcing Authorization header on Streamable HTTP endpoint."""

    def __init__(self, app, expected_token: str = "secret_mcp_token_123"):
        self.app = app
        self.expected_token = expected_token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8")
            if auth_header != f"Bearer {self.expected_token}":
                response = PlainTextResponse("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def get_free_port() -> int:
    """Find a random free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
async def authenticated_mcp_http_server():
    """Spin up local authenticated Streamable HTTP MCP server in background."""
    port = get_free_port()
    base_app = create_base_app()
    app = AuthCheckMiddleware(base_app, expected_token="secret_mcp_token_123")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    for _ in range(30):
        await asyncio.sleep(0.1)
        if server.started:
            break

    url = f"http://127.0.0.1:{port}/mcp"
    yield url

    server.should_exit = True
    await server_task


@pytest.mark.asyncio
async def test_streamable_http_auth_enforcement(authenticated_mcp_http_server: str):
    """
    Verify authenticated Streamable HTTP transport:
    - No auth -> tool discovery fails (failure isolated, 0 tools registered)
    - Configured auth -> tool discovery succeeds, tools registered
    - Tool invocation with auth -> executes and returns correct result
    """
    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)

    # 1. Test unauthenticated request: missing Authorization header
    unauth_config = MCPServerConfig(
        id="unauth-http-server",
        name="Unauthenticated HTTP Server",
        transport=MCPTransportType.STREAMABLE_HTTP,
        url=authenticated_mcp_http_server,
        headers={},  # Missing Authorization
        timeout_seconds=5.0,
    )
    manager.register_server(unauth_config)

    # Discovery should fail gracefully and return empty list due to crash isolation
    unauth_tools = await manager.discover_tools("unauth-http-server")
    assert len(unauth_tools) == 0, f"Expected 0 tools without auth, got {len(unauth_tools)}"

    # 2. Test authenticated request: valid Authorization header
    auth_config = MCPServerConfig(
        id="auth-http-server",
        name="Authenticated HTTP Server",
        transport=MCPTransportType.STREAMABLE_HTTP,
        url=authenticated_mcp_http_server,
        headers={"Authorization": "Bearer secret_mcp_token_123"},
        timeout_seconds=5.0,
    )
    manager.register_server(auth_config)

    # Discovery should succeed and register tools
    auth_tools = await manager.discover_tools("auth-http-server")
    assert len(auth_tools) > 0, "Expected tools to be discovered with valid authorization!"
    tool_names = [t.name for t in auth_tools]
    assert "mcp_auth-http-server_http_echo" in tool_names
    assert "mcp_auth-http-server_http_add" in tool_names

    # 3. Test tool invocation with authentication
    res = await manager.call_tool(
        server_id="auth-http-server",
        tool_name="http_echo",
        arguments={"message": "secret-authenticated-message"},
    )
    assert res.success is True
    assert "http-echo: secret-authenticated-message" in res.output

    # 4. Clean disconnect
    await manager.disconnect_all()
