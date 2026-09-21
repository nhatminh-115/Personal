"""Domain models and Pydantic schemas for AURA Routing Profiles."""

from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field, model_validator

from app.models.base import FallbackPolicy, PrivacyPolicy, ReasoningEffort, ReasoningPolicy


class ReasoningConfig(BaseModel):
    """Reasoning policy configuration for a specific route."""
    
    policy: ReasoningPolicy = ReasoningPolicy.FIXED
    effort: ReasoningEffort = ReasoningEffort.LOW
    min_effort: Optional[ReasoningEffort] = None
    max_effort: Optional[ReasoningEffort] = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "ReasoningConfig":
        if self.policy == ReasoningPolicy.ADAPTIVE:
            if not self.min_effort or not self.max_effort:
                raise ValueError("Adaptive reasoning policy requires both min_effort and max_effort to be set.")
        return self


class RouteConfig(BaseModel):
    """Configuration for a specific task type or role route."""
    
    model_override: Optional[str] = None  # e.g., "openai:gpt-4o" or "auto"
    provider_override: Optional[str] = None
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    privacy_policy: Optional[PrivacyPolicy] = None
    fallback_policy: Optional[FallbackPolicy] = None


class RoutingProfile(BaseModel):
    """Typed representation of a Routing Profile."""
    
    id: Optional[str] = None
    name: str
    version: int = 1
    is_active: bool = True
    
    global_privacy_policy: PrivacyPolicy = PrivacyPolicy.PUBLIC
    global_fallback_policy: FallbackPolicy = FallbackPolicy.CLOUD_ALLOWED
    cost_preference: Literal["low", "normal"] = "normal"
    latency_preference: Literal["low", "normal"] = "normal"
    
    # role/task -> RouteConfig (e.g. "root", "research", "coding")
    routes: Dict[str, RouteConfig] = Field(default_factory=dict)
