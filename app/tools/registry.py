"""Central registry for managing available tools."""

from typing import Dict, List, Optional
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

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

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
