"""Ensure unexpected tool exceptions stay out of messages, state, and traces."""

import json
from typing import Any, Dict, Optional

import pytest

from app.approvals.capabilities import Capability
from app.core.errors import WorkspaceEscapeError
from app.orchestrator.nodes import execute_tool_node
from app.tools.base import RiskLevel, Tool, ToolResult


class RaisingTool(Tool):
    def __init__(self, error: Exception) -> None:
        self.error = error

    @property
    def name(self) -> str:
        return "raising_test_tool"

    @property
    def description(self) -> str:
        return "Raises an exception for tool-boundary tests."

    @property
    def required_capabilities(self) -> list[str]:
        return [Capability.FILESYSTEM_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        raise self.error


class SingleToolRegistry:
    def __init__(self, tool: Tool) -> None:
        self.tool = tool

    def get(self, name: str) -> Optional[Tool]:
        return self.tool if name == self.tool.name else None


class RecordingTraceService:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def record_event(self, **event) -> None:
        self.events.append(event)


def make_state() -> dict:
    return {
        "run_id": "tool-error-run",
        "session_id": "tool-error-session",
        "tool_requests": [{"name": "raising_test_tool", "id": "tool-call-1", "arguments": {}}],
        "tool_approvals": {},
        "messages": [],
        "errors": [],
        "step_number": 1,
        "total_tool_calls": 0,
        "consecutive_failures": 0,
    }


@pytest.mark.asyncio
async def test_unexpected_tool_exception_is_redacted_from_state_message_and_trace():
    diagnostic = "private service endpoint https://user:secret@internal.example/path"
    trace_service = RecordingTraceService()
    tool = RaisingTool(RuntimeError(diagnostic))

    result = await execute_tool_node(
        make_state(),
        {"configurable": {"tool_registry": SingleToolRegistry(tool), "trace_service": trace_service}},
    )

    tool_result = result["tool_results"][0]["result"]
    assert tool_result == {
        "success": False,
        "output": "",
        "error": "Tool execution failed because an internal error occurred.",
        "error_category": "tool_failure",
        "metadata": {"error_type": "RuntimeError"},
    }
    assert result["errors"] == ["tool_failure: RuntimeError"]
    assert "internal error occurred" in result["messages"][-1]["content"]
    assert result["consecutive_failures"] == 1
    assert diagnostic not in json.dumps(
        {"result": result, "events": trace_service.events},
        default=str,
    )


@pytest.mark.asyncio
async def test_workspace_boundary_denial_keeps_its_permission_category():
    denial = "ACCESS DENIED: Path traversal outside workspace boundary. Target: '../secret.txt'"
    tool = RaisingTool(WorkspaceEscapeError(denial))

    result = await execute_tool_node(
        make_state(),
        {"configurable": {"tool_registry": SingleToolRegistry(tool)}},
    )

    tool_result = result["tool_results"][0]["result"]
    assert tool_result["success"] is False
    assert tool_result["error"] == denial
    assert tool_result["error_category"] == "permission_failure"
