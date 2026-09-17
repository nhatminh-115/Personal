"""Integration tests for Milestone 2C: MCP Tool Bus, dynamic discovery, and security policy overlay."""

import sys
import pytest
from app.approvals.capabilities import Capability
from app.approvals.policy import PermissionDecision, PermissionPolicy
from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.mcp.policy import MCPSecurityPolicy
from app.tools.base import RiskLevel
from app.tools.registry import ToolRegistry


@pytest.fixture
def custom_registry():
    return ToolRegistry()


@pytest.fixture
def mcp_fixture_manager(custom_registry):
    policy = MCPSecurityPolicy()
    manager = MCPClientManager(registry=custom_registry, policy=policy)
    # Register the local stdio test fixture server
    config = MCPServerConfig(
        id="fixture_srv",
        name="Fixture Server",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        timeout_seconds=15.0,
        read_only=False,
        auto_approve_tools=["read_metric"],
        high_risk_tools=["mutate_record"],
    )
    manager.register_server(config)
    return manager


@pytest.mark.asyncio
async def test_mcp_discovery_and_registration(mcp_fixture_manager, custom_registry):
    """Verify dynamic discovery connects via stdio, queries tools, and registers them into ToolRegistry."""
    tools = await mcp_fixture_manager.discover_tools("fixture_srv")
    assert len(tools) >= 4

    tool_names = [t.name for t in tools]
    assert "mcp_fixture_srv_read_metric" in tool_names
    assert "mcp_fixture_srv_system_echo" in tool_names
    assert "mcp_fixture_srv_mutate_record" in tool_names
    assert "mcp_fixture_srv_failing_tool" in tool_names

    # Check they are in custom_registry
    for name in tool_names:
        assert custom_registry.get(name) is not None

    # Check LLM tool definitions are correctly exported
    defs = custom_registry.get_tool_definitions()
    def_names = [d.name for d in defs]
    assert "mcp_fixture_srv_read_metric" in def_names


@pytest.mark.asyncio
async def test_mcp_security_policy_and_permissions(mcp_fixture_manager):
    """Verify security policy assigns appropriate risk levels and permission policy gates execution."""
    await mcp_fixture_manager.discover_tools("fixture_srv")
    perm_policy = PermissionPolicy()

    # 1. read_metric was in auto_approve_tools and has no mutation terms -> LOW risk, AUTOMATIC
    read_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_read_metric")
    assert read_tool is not None
    assert read_tool.risk_level == RiskLevel.LOW
    assert Capability.MCP_READ.value in read_tool.required_capabilities
    decision_read = perm_policy.evaluate(read_tool.required_capabilities, read_tool.risk_level.value)
    assert decision_read == PermissionDecision.AUTOMATIC

    # 2. mutate_record contains mutation terms and in high_risk_tools -> HIGH risk, REQUIRES_APPROVAL
    mutate_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_mutate_record")
    assert mutate_tool is not None
    assert mutate_tool.risk_level == RiskLevel.HIGH
    assert Capability.MCP_EXECUTE.value in mutate_tool.required_capabilities
    decision_mutate = perm_policy.evaluate(mutate_tool.required_capabilities, mutate_tool.risk_level.value)
    assert decision_mutate == PermissionDecision.REQUIRES_APPROVAL

    # 3. system_echo has no whitelist -> default HIGH risk, REQUIRES_APPROVAL
    echo_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_system_echo")
    assert echo_tool is not None
    assert echo_tool.risk_level == RiskLevel.HIGH
    decision_echo = perm_policy.evaluate(echo_tool.required_capabilities, echo_tool.risk_level.value)
    assert decision_echo == PermissionDecision.REQUIRES_APPROVAL


@pytest.mark.asyncio
async def test_mcp_input_schema_validation(mcp_fixture_manager):
    """Verify that malformed inputs are caught locally by schema validation without calling server."""
    await mcp_fixture_manager.discover_tools("fixture_srv")
    read_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_read_metric")

    # Missing required argument 'metric_name'
    result = await read_tool.execute({})
    assert result.success is False
    assert "Schema validation failed" in result.error
    assert result.metadata.get("error_category") == "validation_error"


@pytest.mark.asyncio
async def test_mcp_successful_tool_execution(mcp_fixture_manager):
    """Verify end-to-end execution of an MCP tool via stdio transport."""
    await mcp_fixture_manager.discover_tools("fixture_srv")
    read_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_read_metric")

    result = await read_tool.execute({"metric_name": "cpu_utilization"})
    assert result.success is True
    assert "cpu_utilization" in result.output
    assert "99.9%" in result.output


@pytest.mark.asyncio
async def test_mcp_server_level_failure_isolation(mcp_fixture_manager):
    """Verify that a crashing or failing MCP tool returns a structured error and does not take down the runtime."""
    await mcp_fixture_manager.discover_tools("fixture_srv")
    fail_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_failing_tool")

    # Call the crashing tool
    result = await fail_tool.execute({})
    assert result.success is False
    assert "Internal simulated MCP failure" in result.error or "error" in result.error.lower()

    # Prove runtime is still healthy and subsequent tool calls succeed
    read_tool = mcp_fixture_manager.registry.get("mcp_fixture_srv_read_metric")
    healthy_res = await read_tool.execute({"metric_name": "disk_space"})
    assert healthy_res.success is True
    assert "disk_space" in healthy_res.output


@pytest.mark.asyncio
async def test_mcp_nonexistent_or_broken_server_isolation():
    """Verify that registering a broken server does not crash discovery or tool execution."""
    broken_manager = MCPClientManager()
    broken_config = MCPServerConfig(
        id="broken_srv",
        name="Broken Server",
        transport=MCPTransportType.STDIO,
        command="non_existent_executable_binary_12345",
        args=[],
        timeout_seconds=2.0,
    )
    broken_manager.register_server(broken_config)

    # Discovery should safely return empty list without crashing
    tools = await broken_manager.discover_tools("broken_srv")
    assert tools == []

    # Direct tool call should return clean failure
    call_res = await broken_manager.call_tool("broken_srv", "dummy_tool", {})
    assert call_res.success is False
    assert "Server failure" in call_res.error or "not found" in call_res.error.lower()
