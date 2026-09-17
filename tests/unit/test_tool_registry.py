"""Unit tests for tool registration and metadata generation."""

from app.tools.base import RiskLevel
from app.tools.registry import ToolRegistry
from app.tools.workspace import ListWorkspaceFilesTool, ReadWorkspaceFileTool, WriteWorkspaceFileTool


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
