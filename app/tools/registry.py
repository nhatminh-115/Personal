"""Central registry for managing available tools."""

from typing import Dict, List, Optional
from app.capabilities.registry import (
    CapabilityProvider,
    CapabilityProviderMetadata,
    CapabilityProviderRegistry,
    CapabilityProviderHealth,
    NetworkRequirement,
    PrivacyBoundary,
    ProviderApprovalRequirement,
    ProviderPermission,
)
from app.models.base import ToolDefinition
from app.tools.base import Tool
from app.research.tools import (
    ExtractEvidenceTool,
    ReadDocumentSectionTool,
    RecordResearchClaimTool,
    ResearchSearchTool,
    SaveResearchFindingTool,
)
from app.sandbox.tools import SandboxPythonExecuteTool, SandboxShellExecuteTool
from app.tools.delegation import DelegateTaskTool
from app.tools.workspace import (
    ListWorkspaceFilesTool,
    ReadWorkspaceFileTool,
    WriteWorkspaceFileTool,
)


class ToolRegistry:
    """Registry maintaining available tools and their metadata."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self.capability_providers = CapabilityProviderRegistry()
        # Register standard tools
        self.register(ListWorkspaceFilesTool())
        self.register(ReadWorkspaceFileTool())
        self.register(WriteWorkspaceFileTool())
        self.register(SandboxShellExecuteTool())
        self.register(SandboxPythonExecuteTool())
        self.register(DelegateTaskTool())
        # Register research tools
        self.register(ResearchSearchTool())
        self.register(ReadDocumentSectionTool())
        self.register(ExtractEvidenceTool())
        self.register(RecordResearchClaimTool())
        self.register(SaveResearchFindingTool())

        self.register_capability_provider(
            CapabilityProviderMetadata(
                provider_id="aura.workspace",
                name="AURA Workspace",
                health=CapabilityProviderHealth.UNKNOWN,
                capabilities=["workspace.files.read", "workspace.files.write"],
                privacy_boundary=PrivacyBoundary.LOCAL,
                network_requirement=NetworkRequirement.NONE,
                data_touched=["workspace_files"],
                permissions=[ProviderPermission.READ, ProviderPermission.WRITE],
                approval_requirement=ProviderApprovalRequirement.PER_TOOL_POLICY,
            ),
            {
                "workspace.files.read": ["list_workspace_files", "read_workspace_file"],
                "workspace.files.write": ["write_workspace_file"],
            },
        )
        self.register_capability_provider(
            CapabilityProviderMetadata(
                provider_id="aura.sandbox",
                name="AURA Sandboxed Execution",
                health=CapabilityProviderHealth.UNKNOWN,
                capabilities=["sandbox.execute"],
                privacy_boundary=PrivacyBoundary.LOCAL,
                network_requirement=NetworkRequirement.NONE,
                data_touched=["sandbox_files", "processes"],
                permissions=[ProviderPermission.READ, ProviderPermission.WRITE, ProviderPermission.EXECUTE],
                approval_requirement=ProviderApprovalRequirement.PER_TOOL_POLICY,
            ),
            {"sandbox.execute": ["sandbox_shell_execute", "sandbox_python_execute"]},
        )
        self.register_capability_provider(
            CapabilityProviderMetadata(
                provider_id="aura.research",
                name="AURA Research Sources",
                health=CapabilityProviderHealth.UNKNOWN,
                capabilities=["research.search", "research.sources.read", "research.evidence.extract", "research.claims.write"],
                privacy_boundary=PrivacyBoundary.UNKNOWN,
                network_requirement=NetworkRequirement.UNKNOWN,
                data_touched=["research_queries", "public_sources", "project_research_state"],
                permissions=[ProviderPermission.READ, ProviderPermission.WRITE],
                approval_requirement=ProviderApprovalRequirement.PER_TOOL_POLICY,
            ),
            {
                "research.search": ["research_search"],
                "research.sources.read": ["read_document_section"],
                "research.evidence.extract": ["extract_evidence"],
                "research.claims.write": ["record_research_claim", "save_research_finding"],
            },
        )

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def register_capability_provider(
        self,
        metadata: CapabilityProviderMetadata,
        capability_tools: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Register a provider only when every binding resolves to a canonical AURA tool."""
        bindings = capability_tools or {}
        missing_tools = sorted({name for names in bindings.values() for name in names if name not in self._tools})
        if missing_tools:
            raise ValueError(f"Provider '{metadata.provider_id}' references unregistered tools: {missing_tools}")
        self.capability_providers.register(metadata, bindings)

    def register_provider(self, provider: CapabilityProvider) -> None:
        """Accept any provider implementing the typed metadata/binding boundary."""
        self.register_capability_provider(
            provider.metadata,
            {capability: list(names) for capability, names in provider.capability_tools.items()},
        )

    def unregister_capability_provider(self, provider_id: str) -> None:
        self.capability_providers.unregister(provider_id)

    def resolve_capabilities(
        self,
        capabilities: List[str],
        allowed_tool_names: Optional[List[str]] = None,
    ) -> List[str]:
        return self.capability_providers.resolve_tools(capabilities, allowed_tool_names)

    def resolve_available_capabilities(
        self,
        capabilities: List[str],
        allowed_tool_names: Optional[List[str]] = None,
    ) -> List[str]:
        return self.capability_providers.resolve_available_tools(capabilities, allowed_tool_names)

    def get(self, name: str) -> Optional[Tool]:
        """Lookup tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[Tool]:
        """Return list of all registered tools."""
        return list(self._tools.values())

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Export tool definitions formatted for model function-calling."""
        return [tool.to_tool_definition() for tool in self._tools.values()]


# Global singleton tool registry
tool_registry = ToolRegistry()
