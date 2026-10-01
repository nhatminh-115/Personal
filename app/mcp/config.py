"""Configuration models for Model Context Protocol (MCP) servers."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from app.capabilities.registry import (
    NetworkRequirement,
    PrivacyBoundary,
    ProviderApprovalRequirement,
    ProviderPermission,
)


class MCPTransportType(str, Enum):
    """Supported transport protocols for MCP servers."""
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"
    HTTP = "http"  # Alias for streamable-http
    SSE = "sse"  # Legacy Server-Sent Events compatibility transport


class MCPServerConfig(BaseModel):
    """Configuration definition for an external MCP server."""

    id: str = Field(..., pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$", description="Unique alphanumeric identifier for the server (e.g. 'github', 'filesystem').")
    name: str = Field(..., description="Human-readable server name.")
    transport: MCPTransportType = Field(default=MCPTransportType.STDIO, description="Transport type (stdio, sse, http).")
    
    # STDIO transport configuration
    command: Optional[str] = Field(None, description="Command to execute for stdio transport (e.g. 'python', 'npx').")
    args: List[str] = Field(default_factory=list, description="Command-line arguments for stdio transport.")
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variable overrides for stdio subprocess.")
    cwd: Optional[str] = Field(None, description="Working directory for the stdio process.")

    # Network / SSE transport configuration
    url: Optional[str] = Field(None, description="Endpoint URL for SSE/HTTP transport.")
    headers: Dict[str, str] = Field(default_factory=dict, description="HTTP headers for remote requests.")

    # Execution controls and safety limits
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0, description="Execution timeout for tool calls.")
    enabled: bool = Field(default=True, description="Whether this server is active.")
    allowed_tools: Optional[List[str]] = Field(None, description="Explicit whitelist of allowed tools. If None, all tools discovered are processed.")

    # Policy overrides
    read_only: bool = Field(default=False, description="If True, treats all server tools as read-only operations.")
    auto_approve_tools: List[str] = Field(default_factory=list, description="Tool names explicitly allowed to run automatically without human interruption.")
    high_risk_tools: List[str] = Field(default_factory=list, description="Tool names explicitly marked as HIGH risk.")

    # Explicit capability-provider facts. Unknown values remain unknown; AURA does not infer them from server names.
    provider_version: Optional[str] = Field(None, max_length=80)
    capabilities_by_tool: Dict[str, List[str]] = Field(default_factory=dict)
    privacy_boundary: PrivacyBoundary = PrivacyBoundary.UNKNOWN
    network_requirement: NetworkRequirement = NetworkRequirement.UNKNOWN
    data_touched: Optional[List[str]] = None
    permissions: Optional[List[ProviderPermission]] = None
    approval_requirement: ProviderApprovalRequirement = ProviderApprovalRequirement.PER_TOOL_POLICY

    @model_validator(mode="after")
    def validate_capability_mappings(self) -> "MCPServerConfig":
        """Reject capability mappings that cannot survive the configured allowlist."""
        invalid_tools = [name for name in self.capabilities_by_tool if not name.strip()]
        if invalid_tools:
            raise ValueError("capabilities_by_tool keys must be non-empty MCP tool names.")
        empty_capabilities = [
            name for name, capabilities in self.capabilities_by_tool.items()
            if not capabilities or any(not capability.strip() for capability in capabilities)
        ]
        if empty_capabilities:
            raise ValueError(
                "Each capabilities_by_tool entry must declare non-empty capability names: "
                f"{sorted(empty_capabilities)}"
            )
        if self.allowed_tools is not None:
            excluded = sorted(set(self.capabilities_by_tool) - set(self.allowed_tools))
            if excluded:
                raise ValueError(
                    "Capability mappings must reference tools included in allowed_tools: "
                    f"{excluded}"
                )
        return self
