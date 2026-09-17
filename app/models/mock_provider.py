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

        # If previous message is a TOOL result, summarize it
        if latest_msg.role == ModelRole.TOOL:
            return ModelResponse(
                content=f"Based on the tool output: {latest_msg.content}",
                usage=ModelUsage(prompt_tokens=25, completion_tokens=15, total_tokens=40),
                finish_reason="stop",
            )

        content = latest_msg.content.strip()

        # Check for tool invocations requested by user query
        # 1. "Read <path>" or "Read file <path>"
        read_match = re.search(r"read\s+(?:file\s+)?([^\s]+)", content, re.IGNORECASE)
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

        # 2. "Write <content> to <path>"
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

        # 3. "List files" or "List directory"
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

        # Direct conversational response
        return ModelResponse(
            content=f"AURA Response: Processed '{content}' successfully.",
            usage=ModelUsage(prompt_tokens=15, completion_tokens=10, total_tokens=25),
            finish_reason="stop",
        )
