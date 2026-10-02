"""Typed capability-provider inventory and control-plane API invariants."""

import sys

import pytest
from pydantic import ValidationError

from app.capabilities.registry import (
    CapabilityProviderHealth,
    CapabilityProviderMetadata,
    NetworkRequirement,
    PrivacyBoundary,
)
from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_provider_inventory_exposes_metadata_without_runtime_secrets(async_client):
    response = await async_client.get("/v1/capabilities/providers")
    assert response.status_code == 200
    providers = {provider["provider_id"]: provider for provider in response.json()["providers"]}
    assert {"aura.workspace", "aura.sandbox", "aura.research"} <= providers.keys()

    workspace = providers["aura.workspace"]
    assert workspace["privacy_boundary"] == "local"
    assert workspace["network_requirement"] == "none"
    assert workspace["capabilities"] == ["workspace.files.read", "workspace.files.write"]
    assert workspace["capability_tools"] == {
        "workspace.files.read": ["list_workspace_files", "read_workspace_file"],
        "workspace.files.write": ["write_workspace_file"],
    }
    research = providers["aura.research"]
    assert research["privacy_boundary"] == "unknown"
    assert research["network_requirement"] == "unknown"
    serialized = response.text
    assert "authorization" not in serialized.lower()
    assert "api_key" not in serialized.lower()
    assert "internal.example" not in serialized
    assert "sensitive-token" not in serialized


def test_mcp_provider_inventory_uses_explicit_facts_and_capability_mappings():
    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)
    config = MCPServerConfig(
        id="docs",
        name="Document service",
        transport=MCPTransportType.STREAMABLE_HTTP,
        url="https://internal.example/mcp",
        headers={"Authorization": "sensitive-token"},
        capabilities_by_tool={"find_documents": ["research.library.search"]},
    )
    manager.register_server(config)

    provider = registry.capability_providers.get("mcp.docs")
    assert provider is not None
    assert provider.health == CapabilityProviderHealth.UNKNOWN
    assert provider.privacy_boundary == PrivacyBoundary.UNKNOWN
    assert provider.network_requirement == NetworkRequirement.UNKNOWN
    assert provider.capabilities == ["research.library.search"]
    bindings = registry.capability_providers.get_capability_tools("mcp.docs")
    assert bindings == {"research.library.search": ["find_documents"]}
    bindings["research.library.search"].append("mutated")
    assert registry.capability_providers.get_capability_tools("mcp.docs") == {"research.library.search": ["find_documents"]}
    assert registry.resolve_available_capabilities(["research.library.search"]) == []
    assert "sensitive-token" not in provider.model_dump_json()


def test_mcp_capability_mappings_must_be_non_empty_and_inside_tool_allowlist():
    with pytest.raises(ValidationError, match="included in allowed_tools"):
        MCPServerConfig(
            id="invalid-map",
            name="Invalid map",
            allowed_tools=["codegraph_symbol_search"],
            capabilities_by_tool={"codegraph_analyze_impact": ["code_graph.impact"]},
        )

    with pytest.raises(ValidationError, match="non-empty capability names"):
        MCPServerConfig(
            id="empty-map",
            name="Empty map",
            capabilities_by_tool={"tool": []},
        )

    valid = MCPServerConfig(
        id="valid-map",
        name="Valid map",
        allowed_tools=["codegraph_symbol_search"],
        capabilities_by_tool={"codegraph_symbol_search": ["code_graph.query"]},
    )
    assert valid.capabilities_by_tool["codegraph_symbol_search"] == ["code_graph.query"]


def test_mcp_manager_isolates_registered_config_from_mutable_callers():
    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)
    config = MCPServerConfig(
        id="isolated-config",
        name="Isolated config",
        allowed_tools=["read_document"],
        env={"TOKEN": "initial"},
        headers={"Authorization": "initial"},
        capabilities_by_tool={"read_document": ["research.library.read"]},
    )
    manager.register_server(config)

    config.enabled = False
    config.allowed_tools.append("delete_document")
    config.env["TOKEN"] = "changed"
    config.capabilities_by_tool["read_document"].append("workspace.files.write")

    fetched = manager.get_server_config("isolated-config")
    assert fetched is not None
    assert fetched.enabled is True
    assert fetched.allowed_tools == ["read_document"]
    assert fetched.env == {"TOKEN": "initial"}
    assert fetched.capabilities_by_tool == {"read_document": ["research.library.read"]}

    fetched.enabled = False
    fetched.headers["Authorization"] = "read-mutation"
    listed = manager.list_servers()[0]
    listed.allowed_tools.append("delete_document")

    confirmed = manager.get_server_config("isolated-config")
    assert confirmed is not None
    assert confirmed.enabled is True
    assert confirmed.allowed_tools == ["read_document"]
    assert confirmed.headers == {"Authorization": "initial"}


@pytest.mark.asyncio
async def test_mcp_capability_requires_discovery_of_its_declared_tool():
    from app.capabilities.registry import UnresolvedCapabilitiesError

    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)
    manager.register_server(MCPServerConfig(
        id="graph-fixture",
        name="Graph fixture",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        timeout_seconds=10.0,
        capabilities_by_tool={"codegraph_missing_impact": ["code_graph.impact"]},
    ))

    configured = registry.capability_providers.get("mcp.graph-fixture")
    assert configured is not None and configured.health == CapabilityProviderHealth.UNKNOWN
    assert registry.resolve_available_capabilities(["code_graph.impact"]) == []

    await manager.discover_tools("graph-fixture")
    discovered = registry.capability_providers.get("mcp.graph-fixture")
    assert discovered is not None and discovered.health == CapabilityProviderHealth.DEGRADED
    assert registry.resolve_available_capabilities(["code_graph.impact"]) == []
    with pytest.raises(UnresolvedCapabilitiesError):
        registry.resolve_capabilities(["code_graph.impact"])
    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_discovered_mcp_capability_reaches_coding_runtime_and_executes():
    from app.delegation.registry import specialist_registry
    from app.delegation.runtime import DelegationRuntime

    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)
    manager.register_server(MCPServerConfig(
        id="graph-fixture",
        name="Graph fixture",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        timeout_seconds=10.0,
        read_only=True,
        allowed_tools=["read_metric"],
        capabilities_by_tool={"read_metric": ["code_graph.query"]},
    ))

    discovered = await manager.discover_tools("graph-fixture")
    runtime = DelegationRuntime(base_tool_registry=registry)
    coding = specialist_registry.get("coding")
    assert coding is not None
    scoped = runtime._resolve_specialist_tools(coding)
    tool_name = "mcp_graph-fixture_read_metric"
    assert tool_name in scoped
    assert registry.capability_providers.get("mcp.graph-fixture").health == CapabilityProviderHealth.HEALTHY

    adapter = next(tool for tool in discovered if tool.name == tool_name)
    result = await adapter.execute({"metric_name": "graph_nodes"})
    assert result.success is True
    assert "graph_nodes" in result.output

    await manager.disconnect_all()


@pytest.mark.asyncio
async def test_mcp_canonical_name_collision_does_not_replace_an_existing_provider_tool():
    registry = ToolRegistry()
    manager = MCPClientManager(registry=registry)
    manager.register_server(MCPServerConfig(
        id="graph_provider",
        name="First graph provider",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        timeout_seconds=10.0,
        read_only=True,
        allowed_tools=["read_metric"],
        capabilities_by_tool={"read_metric": ["code_graph.query"]},
    ))
    manager.register_server(MCPServerConfig(
        id="graph",
        name="Second graph provider",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        timeout_seconds=10.0,
        read_only=True,
        allowed_tools=["provider_read_metric"],
        capabilities_by_tool={"provider_read_metric": ["code_graph.impact"]},
    ))

    first_tools = await manager.discover_tools("graph_provider")
    first_name = "mcp_graph_provider_read_metric"
    original = registry.get(first_name)
    assert any(tool.name == first_name for tool in first_tools)
    assert original is not None

    second_tools = await manager.discover_tools("graph")
    assert second_tools == []
    assert registry.get(first_name) is original
    assert registry.resolve_available_capabilities(["code_graph.query"]) == [first_name]
    assert registry.resolve_available_capabilities(["code_graph.impact"]) == []

    await manager.disconnect_all()


def test_specialists_request_abstract_capabilities_and_unresolved_provider_stays_blocked():
    from app.delegation.registry import specialist_registry
    from app.tools.registry import tool_registry
    from app.capabilities.registry import UnresolvedCapabilitiesError

    coding = specialist_registry.get("coding")
    research = specialist_registry.get("research")
    assert coding is not None and coding.allowed_tools == []
    assert research is not None and research.allowed_tools == []
    assert coding.optional_runtime_capabilities == [
        "code_graph.context", "code_graph.query", "code_graph.impact", "code_graph.trace",
    ]
    assert "When code-graph tools are present" in coding.system_prompt_template
    assert "if none are available, continue" in coding.system_prompt_template
    coding_tools = set(tool_registry.resolve_capabilities(coding.requested_runtime_capabilities))
    research_tools = set(tool_registry.resolve_capabilities(research.requested_runtime_capabilities))
    assert {"read_workspace_file", "write_workspace_file", "sandbox_shell_execute"} <= coding_tools
    assert "write_workspace_file" not in research_tools

    with pytest.raises(UnresolvedCapabilitiesError):
        tool_registry.resolve_capabilities(["browser.control"])


def test_optional_code_graph_tools_are_exposed_only_when_a_provider_is_available():
    from app.delegation.registry import specialist_registry
    from app.delegation.runtime import DelegationRuntime
    from app.tools.registry import ToolRegistry

    registry = ToolRegistry()
    coding = specialist_registry.get("coding")
    assert coding is not None
    runtime = DelegationRuntime(base_tool_registry=registry)

    required = set(registry.resolve_capabilities(coding.requested_runtime_capabilities))
    assert set(runtime._resolve_specialist_tools(coding)) == required
    assert registry.resolve_available_capabilities(coding.optional_runtime_capabilities) == []

    registry.register_capability_provider(
        CapabilityProviderMetadata(
            provider_id="mcp.codegraph",
            name="CodeGraph MCP",
            health=CapabilityProviderHealth.UNKNOWN,
            capabilities=["code_graph.context", "code_graph.impact"],
            privacy_boundary=PrivacyBoundary.LOCAL,
            network_requirement=NetworkRequirement.UNKNOWN,
        ),
        {
            "code_graph.context": ["read_workspace_file"],
            "code_graph.impact": ["list_workspace_files"],
        },
    )

    exposed = set(runtime._resolve_specialist_tools(coding))
    assert required <= exposed
    assert {"read_workspace_file", "list_workspace_files"} <= exposed
    assert registry.resolve_available_capabilities(["code_graph.trace"]) == []

    registry.register_capability_provider(
        CapabilityProviderMetadata(
            provider_id="mcp.disabled",
            name="Disabled provider",
            enabled=False,
            health=CapabilityProviderHealth.DISABLED,
            capabilities=["code_graph.trace"],
        ),
        {"code_graph.trace": ["read_workspace_file"]},
    )
    assert registry.resolve_available_capabilities(["code_graph.trace"]) == []


def test_native_or_external_provider_can_implement_the_typed_provider_boundary():
    registry = ToolRegistry()

    class LocalSearchProvider:
        metadata = CapabilityProviderMetadata(
            provider_id="test.search",
            name="Test Search Provider",
            capabilities=["web_search.query"],
            health=CapabilityProviderHealth.UNKNOWN,
        )
        capability_tools = {"web_search.query": ["research_search"]}

    registry.register_provider(LocalSearchProvider())
    assert registry.resolve_capabilities(["web_search.query"]) == ["research_search"]


def test_provider_metadata_isolated_from_mutable_registration_and_read_models():
    registry = ToolRegistry()
    metadata = CapabilityProviderMetadata(
        provider_id="test.immutable",
        name="Immutable metadata",
        capabilities=["test.read"],
        data_touched=["workspace_files"],
    )
    registry.register_capability_provider(metadata, {"test.read": ["read_workspace_file"]})

    metadata.capabilities.append("test.unregistered")
    metadata.data_touched.append("secrets")
    stored = registry.capability_providers.get("test.immutable")
    assert stored is not None
    assert stored.capabilities == ["test.read"]
    assert stored.data_touched == ["workspace_files"]

    stored.capabilities.append("test.read.unreviewed")
    stored_list = registry.capability_providers.list_providers()
    returned = next(item for item in stored_list if item.provider_id == "test.immutable")
    returned.data_touched.append("secrets")
    confirmed = registry.capability_providers.get("test.immutable")
    assert confirmed is not None
    assert confirmed.capabilities == ["test.read"]
    assert confirmed.data_touched == ["workspace_files"]
