"""Unit tests for tool registration and metadata generation."""

from app.tools.base import RiskLevel
from app.tools.registry import ToolRegistry
from app.tools.workspace import ListWorkspaceFilesTool, ReadWorkspaceFileTool, WriteWorkspaceFileTool
from app.capabilities.registry import (
    CapabilityProviderHealth,
    CapabilityProviderMetadata,
    NetworkRequirement,
    PrivacyBoundary,
    UnresolvedCapabilitiesError,
)


def test_standard_tools_registered():
    registry = ToolRegistry()
    tools = registry.list_tools()

    tool_names = {t.name for t in tools}
    assert "list_workspace_files" in tool_names
    assert "read_workspace_file" in tool_names
    assert "write_workspace_file" in tool_names


def test_tool_definitions_for_llm():
    registry = ToolRegistry()
    definitions = registry.get_tool_definitions()

    assert len(definitions) >= 3
    write_def = next(d for d in definitions if d.name == "write_workspace_file")
    assert write_def.description != ""
    assert "path" in write_def.parameters["properties"]
    assert "content" in write_def.parameters["properties"]


def test_tool_risk_levels():
    registry = ToolRegistry()
    read_tool = registry.get("read_workspace_file")
    write_tool = registry.get("write_workspace_file")

    assert read_tool is not None
    assert read_tool.risk_level == RiskLevel.LOW

    assert write_tool is not None
    assert write_tool.risk_level == RiskLevel.HIGH


def test_abstract_capabilities_resolve_only_to_explicit_provider_bindings():
    registry = ToolRegistry()
    assert set(registry.resolve_capabilities(["workspace.files.read"])) == {
        "list_workspace_files", "read_workspace_file",
    }
    assert registry.resolve_capabilities(["sandbox.execute"]) == [
        "sandbox_shell_execute", "sandbox_python_execute",
    ]
    assert "write_workspace_file" not in registry.resolve_capabilities(["workspace.files.read"])
    try:
        registry.resolve_capabilities(["browser.control"])
    except UnresolvedCapabilitiesError as exc:
        assert exc.capabilities == ["browser.control"]
    else:
        raise AssertionError("Unimplemented abstract capability must not silently resolve.")
    try:
        registry.resolve_capabilities(["sandbox.execute"], allowed_tool_names=["read_workspace_file"])
    except UnresolvedCapabilitiesError as exc:
        assert exc.capabilities == ["sandbox.execute"]
    else:
        raise AssertionError("A concrete tool ceiling must not silently erase a requested capability.")


def test_native_provider_metadata_keeps_unknown_environment_facts_unknown():
    registry = ToolRegistry()
    research = registry.capability_providers.get("aura.research")
    assert research is not None
    assert research.privacy_boundary == PrivacyBoundary.UNKNOWN
    assert research.network_requirement == NetworkRequirement.UNKNOWN
    assert research.health == CapabilityProviderHealth.UNKNOWN


def test_provider_registration_rejects_undeclared_capabilities_and_unknown_tools():
    registry = ToolRegistry()
    metadata = CapabilityProviderMetadata(provider_id="test.provider", name="Test", capabilities=["test.read"])
    try:
        registry.register_capability_provider(metadata, {"test.write": ["read_workspace_file"]})
    except ValueError as exc:
        assert "undeclared capabilities" in str(exc)
    else:
        raise AssertionError("Provider cannot bind a capability it does not declare.")

    try:
        registry.register_capability_provider(metadata, {"test.read": ["missing_tool"]})
    except ValueError as exc:
        assert "unregistered tools" in str(exc)
    else:
        raise AssertionError("Provider cannot bind a missing tool.")
