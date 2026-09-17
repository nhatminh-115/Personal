"""Sample MCP Server fixture for integration tests using mcp 2.x."""

import sys
from mcp.server.mcpserver import MCPServer

# Initialize server
server = MCPServer("test-fixture-server")


@server.tool()
def read_metric(metric_name: str) -> str:
    """Read a system telemetry metric."""
    return f"Metric '{metric_name}' is 99.9%"


@server.tool()
def system_echo(message: str) -> str:
    """Echo input string back to caller."""
    return f"echo: {message}"


@server.tool()
def mutate_record(record_id: str, new_value: str) -> str:
    """Modify a persistent database record."""
    return f"Record {record_id} updated to {new_value}"


@server.tool()
def inspect_env(var_name: str) -> str:
    """Read an environment variable value from the MCP server process."""
    import os
    return os.environ.get(var_name, "__NOT_SET__")


@server.tool()
def failing_tool() -> str:
    """Simulate an internal server crash/exception."""
    raise RuntimeError("Internal simulated MCP failure!")


if __name__ == "__main__":
    server.run(transport="stdio")
