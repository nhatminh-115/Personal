"""Scoped tool registry for sandboxed specialist agents."""

from typing import List, Optional, Set
from app.core.errors import ToolError
from app.models.base import ToolDefinition
from app.tools.base import Tool
from app.tools.registry import ToolRegistry


class ScopedToolRegistry:
    """A restricted view of ToolRegistry scoped strictly to allowed tools for a specialist.
    
    Guarantees that specialist agents cannot access unauthorized tools or re-delegate.
    """

    DISALLOWED_FOR_SPECIALISTS = {"delegate_task"}

    def __init__(self, base_registry: ToolRegistry, allowed_tools: List[str]) -> None:
        self._base_registry = base_registry
        # Filter out disallowed tools strictly
        self._allowed_tools: Set[str] = {
            t for t in allowed_tools if t not in self.DISALLOWED_FOR_SPECIALISTS
        }

    @property
    def allowed_tool_names(self) -> Set[str]:
        return set(self._allowed_tools)

    def register(self, tool: Tool) -> None:
        """Scoped registries are immutable views; registering directly is disallowed."""
        raise ToolError("Cannot register new tools directly into a ScopedToolRegistry.")

    def get(self, name: str) -> Optional[Tool]:
        """Lookup tool by name, strictly enforcing scope."""
        if name not in self._allowed_tools:
            return None
        return self._base_registry.get(name)

    def list_tools(self) -> List[Tool]:
        """Return list of all scoped tools available in base registry."""
        tools = []
        for name in self._allowed_tools:
            tool = self._base_registry.get(name)
            if tool:
                tools.append(tool)
        return tools

    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Export tool definitions only for the allowed scoped tools."""
        return [tool.to_tool_definition() for tool in self.list_tools()]
