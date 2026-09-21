"""Domain models and DTOs for the provider-neutral model layer."""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ModelRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class PrivacyPolicy(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    LOCAL_ONLY = "local_only"


class FallbackPolicy(str, Enum):
    NONE = "none"
    SAME_PROVIDER_ONLY = "same_provider_only"
    LOCAL_ONLY = "local_only"
    CLOUD_ALLOWED = "cloud_allowed"
    ASK_BEFORE_CLOUD = "ask_before_cloud"


class ReasoningEffort(str, Enum):
    INSTANT = "instant"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class ReasoningPolicy(str, Enum):
    FIXED = "fixed"
    ADAPTIVE = "adaptive"


class ToolCallRequest(BaseModel):
    """Normalized tool call request from an LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """Normalized canonical chat message."""

    model_config = ConfigDict(use_enum_values=True)

    role: ModelRole
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCallRequest] | None = None


class ToolDefinition(BaseModel):
    """Normalized tool specification exposed to models."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RoutingContext(BaseModel):
    """Contextual metadata informing future model selection and routing."""

    task_type: str | None = None
    complexity: Literal["simple", "medium", "complex"] | None = None
    privacy_requirement: PrivacyPolicy = PrivacyPolicy.PUBLIC
    fallback_policy: FallbackPolicy = FallbackPolicy.CLOUD_ALLOWED
    latency_preference: Literal["low", "normal"] | None = None
    cost_preference: Literal["low", "normal"] | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    explicit_model_override: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    
    # Capability Filtering
    requires_tools: bool = False
    requires_vision: bool = False
    requires_structured_output: bool = False
    requires_long_context: bool = False
    
    # Reasoning Policy fields
    reasoning_effort: ReasoningEffort | None = None
    reasoning_policy: ReasoningPolicy | None = None
    reasoning_effort_min: ReasoningEffort | None = None
    reasoning_effort_max: ReasoningEffort | None = None
    
    # Profile / Scope Tracking
    profile_id: str | None = None
    profile_version: int | None = None
    winning_scope: Literal["message", "session", "project", "default", "system"] | None = None
    is_lock_all: bool = False


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
    routing_context: RoutingContext | None = None
    selected_model: str | None = None


class ModelResponse(BaseModel):
    """Normalized response from a model provider."""

    content: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    usage: ModelUsage = Field(default_factory=ModelUsage)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"
