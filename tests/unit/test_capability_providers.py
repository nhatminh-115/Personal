"""Typed capability-provider inventory and control-plane API invariants."""

import pytest

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
    research = providers["aura.research"]
    assert research["privacy_boundary"] == "unknown"
    assert research["network_requirement"] == "unknown"
    serialized = response.text
    assert "authorization" not in serialized.lower()
    assert "api_key" not in serialized.lower()


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
    assert "sensitive-token" not in provider.model_dump_json()


def test_specialists_request_abstract_capabilities_and_unresolved_provider_stays_blocked():
    from app.delegation.registry import specialist_registry
    from app.tools.registry import tool_registry
    from app.capabilities.registry import UnresolvedCapabilitiesError

    coding = specialist_registry.get("coding")
    research = specialist_registry.get("research")
    assert coding is not None and coding.allowed_tools == []
    assert research is not None and research.allowed_tools == []
    coding_tools = set(tool_registry.resolve_capabilities(coding.requested_runtime_capabilities))
    research_tools = set(tool_registry.resolve_capabilities(research.requested_runtime_capabilities))
    assert {"read_workspace_file", "write_workspace_file", "sandbox_shell_execute"} <= coding_tools
    assert "write_workspace_file" not in research_tools

    with pytest.raises(UnresolvedCapabilitiesError):
        tool_registry.resolve_capabilities(["browser.control"])


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
