"""Configuration models for Model Context Protocol (MCP) servers."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MCPTransportType(str, Enum):
    """Supported transport protocols for MCP servers."""
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPServerConfig(BaseModel):
    """Configuration definition for an external MCP server."""

    id: str = Field(..., description="Unique alphanumeric identifier for the server (e.g. 'github', 'filesystem').")
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
