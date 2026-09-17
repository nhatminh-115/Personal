"""Sample MCP Streamable HTTP server fixture for integration tests using mcp 2.x."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("streamable-http-fixture")


@server.tool()
def http_echo(message: str) -> str:
    """Echo input string back over Streamable HTTP."""
    return f"http-echo: {message}"


@server.tool()
def http_add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


@server.tool()
def http_failing_tool() -> str:
    """Simulate tool failure over Streamable HTTP."""
    raise ValueError("Simulated HTTP tool failure")


def create_app():
    """Create Starlette ASGI application exposing /mcp endpoint."""
    return server.streamable_http_app(streamable_http_path="/mcp")


if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8999)
