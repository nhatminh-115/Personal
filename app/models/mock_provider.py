"""Deterministic mock model provider for automated testing and local verification."""

import re
import uuid
from typing import List, Optional
from app.models.base import (
    ChatMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
    ModelUsage,
    ToolCallRequest,
)
from app.models.provider import ModelProvider


class MockModelProvider(ModelProvider):
    """Deterministic, programmable mock model provider."""

    def __init__(self, default_response: Optional[str] = None) -> None:
        self._name = "mock"
        self._default_response = default_response or "This is a deterministic mock response from AURA."
        self._queued_responses: List[ModelResponse] = []
        self._call_history: List[ModelRequest] = []

    @property
    def name(self) -> str:
        return self._name

    def queue_response(self, response: ModelResponse) -> None:
        """Queue an explicit response to be returned on the next generate() call."""
        self._queued_responses.append(response)

    def clear_queue(self) -> None:
        self._queued_responses.clear()

    @property
    def call_history(self) -> List[ModelRequest]:
        return self._call_history

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self._call_history.append(request)

        # 1. Return queued response if available
        if self._queued_responses:
            return self._queued_responses.pop(0)

        # 2. Inspect the latest message to decide mock behavior
        if not request.messages:
            return ModelResponse(
                content=self._default_response,
                usage=ModelUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
                finish_reason="stop",
            )

        latest_msg = request.messages[-1]

        # If latest message is a TOOL result or contains recent tool outputs, summarize it
        tool_msgs = [m for m in request.messages if m.role == ModelRole.TOOL]
        if tool_msgs and latest_msg.role == ModelRole.TOOL:
            combined_tool_output = " | ".join(m.content for m in tool_msgs)
            return ModelResponse(
                content=f"Based on the tool output: {combined_tool_output}",
                usage=ModelUsage(prompt_tokens=25, completion_tokens=15, total_tokens=40),
                finish_reason="stop",
            )
        user_msgs = [m for m in request.messages if m.role == ModelRole.USER]
        content = (user_msgs[-1].content if user_msgs else latest_msg.content).strip()

        # Check for tool invocations requested by user query
        # 1. MCP Read Tool: "Read/query metric <name>"
        metric_match = re.search(r"(?:read|query|get)\s+metric\s+([^\s]+)", content, re.IGNORECASE)
        if metric_match and request.tools:
            metric_tool = next((t for t in request.tools if "read_metric" in t.name), None)
            if metric_tool:
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=metric_tool.name,
                            arguments={"metric_name": metric_match.group(1).strip("\"'")},
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                    finish_reason="tool_calls",
                )

        # 2. "Read <path>" or "Read file <path>"
        read_match = re.search(r"read\s+(?:file\s+)?(?!metric\b)([^\s]+)", content, re.IGNORECASE)
        if read_match and request.tools and any(t.name == "read_workspace_file" for t in request.tools):
            path = read_match.group(1).strip("\"'")
            return ModelResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="read_workspace_file",
                        arguments={"path": path},
                    )
                ],
                usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                finish_reason="tool_calls",
            )

        # 3. "Write <content> to <path>"
        write_match = re.search(r"write\s+(.*?)\s+to\s+([^\s]+)", content, re.IGNORECASE)
        if write_match and request.tools and any(t.name == "write_workspace_file" for t in request.tools):
            text_to_write = write_match.group(1).strip("\"'")
            path = write_match.group(2).strip("\"'")
            return ModelResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="write_workspace_file",
                        arguments={"path": path, "content": text_to_write},
                    )
                ],
                usage=ModelUsage(prompt_tokens=25, completion_tokens=12, total_tokens=37),
                finish_reason="tool_calls",
            )

        # 4. "List files" or "List directory"
        if re.search(r"list\s+(?:workspace\s+)?files", content, re.IGNORECASE) and request.tools and any(t.name == "list_workspace_files" for t in request.tools):
            return ModelResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="list_workspace_files",
                        arguments={"subpath": "."},
                    )
                ],
                usage=ModelUsage(prompt_tokens=15, completion_tokens=8, total_tokens=23),
                finish_reason="tool_calls",
            )

        # 5. MCP Mutate Tool: "Mutate/update record <id> to <val>"
        mutate_match = re.search(r"(?:mutate|update)\s+record\s+([^\s]+)\s+to\s+([^\s]+)", content, re.IGNORECASE)
        if mutate_match and request.tools:
            mutate_tool = next((t for t in request.tools if "mutate_record" in t.name), None)
            if mutate_tool:
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=mutate_tool.name,
                            arguments={
                                "record_id": mutate_match.group(1).strip("\"'"),
                                "new_value": mutate_match.group(2).strip("\"'"),
                            },
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=25, completion_tokens=12, total_tokens=37),
                    finish_reason="tool_calls",
                )

        # 6. Sandbox Execution: "Run code: <code>", "Execute python in sandbox: <code>"
        sandbox_python_match = re.search(r"(?:run|execute)\s+(?:code|python)(?:\s+in\s+sandbox|\s+in\s+docker)?:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if sandbox_python_match and request.tools:
            py_tool = next((t for t in request.tools if t.name in {"sandbox_python_execute", "sandbox_run_code"}), None)
            if py_tool:
                code_str = sandbox_python_match.group(1).strip().strip("`")
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=py_tool.name,
                            arguments={"code": code_str},
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45),
                    finish_reason="tool_calls",
                )

        # 7. Sandbox Shell Execution: "Run shell in sandbox: <command>"
        sandbox_shell_match = re.search(r"(?:run|execute)\s+shell(?:\s+in\s+sandbox|\s+in\s+docker)?:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if sandbox_shell_match and request.tools:
            sh_tool = next((t for t in request.tools if t.name == "sandbox_shell_execute"), None)
            if sh_tool:
                cmd_str = sandbox_shell_match.group(1).strip().strip("`")
                return ModelResponse(
                    content=None,
                    tool_calls=[
                        ToolCallRequest(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            name=sh_tool.name,
                            arguments={"command": cmd_str},
                        )
                    ],
                    usage=ModelUsage(prompt_tokens=30, completion_tokens=15, total_tokens=45),
                    finish_reason="tool_calls",
                )

        # If query asks about version/stack and system context contains it, reflect it in response
        if "what" in content.lower() and any(k in content.lower() for k in ["version", "stack", "language"]):
            sys_msgs = [m for m in request.messages if m.role == ModelRole.SYSTEM]
            for sm in sys_msgs:
                if "Python 3.12" in sm.content:
                    return ModelResponse(
                        content="AURA Response: Project uses Python 3.12.",
                        usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        finish_reason="stop",
                    )
                if "Python 3.11" in sm.content:
                    return ModelResponse(
                        content="AURA Response: Project uses Python 3.11.",
                        usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        finish_reason="stop",
                    )
                if "Go 1.22" in sm.content:
                    return ModelResponse(
                        content="AURA Response: Project uses Go 1.22.",
                        usage=ModelUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                        finish_reason="stop",
                    )

        # Direct conversational response
        return ModelResponse(
            content=f"AURA Response: Processed '{content}' successfully.",
            usage=ModelUsage(prompt_tokens=15, completion_tokens=10, total_tokens=25),
            finish_reason="stop",
        )
