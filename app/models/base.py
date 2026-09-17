"""Domain models and DTOs for the provider-neutral model layer."""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class ModelRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """Normalized chat message."""

    role: ModelRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ToolCallRequest(BaseModel):
    """Normalized tool call request from an LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    """Normalized tool specification exposed to models."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModelUsage(BaseModel):
    """Token usage metrics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelRequest(BaseModel):
    """Normalized input request to a model provider."""

    messages: list[ChatMessage]
    tools: list[ToolDefinition] | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    """Normalized response from a model provider."""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
