"""AURA local security policy overlay for MCP tools."""

import re
from typing import Any, Dict, List, Optional, Tuple
import jsonschema
from jsonschema.exceptions import ValidationError

from app.approvals.capabilities import Capability
from app.core.errors import AURAError
from app.mcp.config import MCPServerConfig
from app.tools.base import RiskLevel


class MCPValidationError(AURAError):
    """Raised when an MCP tool invocation does not adhere to its advertised JSON schema."""
    pass


class MCPSecurityPolicy:
    """
    Enforces AURA's local security boundaries over external MCP tools.
    MCP tools are never inherently trusted:
    - Inputs are strictly validated against tool schemas.
    - Default posture is conservative: high risk with human approval required.
    - Read-only, side-effect-free tools may be whitelisted for automatic execution.
    """

    # Operations that must never be auto-approved regardless of prefixes
    MUTATION_KEYWORDS = {
        "delete", "remove", "drop", "write", "execute", "exec",
        "create", "update", "modify", "kill", "eval", "run", "patch", "post", "put"
    }

    # Common read-only prefixes
    READ_PREFIXES = (
        "get_", "list_", "search_", "query_", "fetch_", "read_", "describe_", "show_"
    )

    def validate_arguments(self, tool_name: str, input_schema: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> None:
        """Validate invocation arguments against the MCP tool's JSON schema."""
        if not input_schema:
            return

        try:
            # Handle draft-07 / draft-2020-12 schema validation
            jsonschema.validate(instance=arguments, schema=input_schema)
        except ValidationError as e:
            raise MCPValidationError(
                f"Schema validation failed for MCP tool '{tool_name}': {e.message} (path: {list(e.path)})"
            )

    def evaluate_tool_security(
        self,
        server_config: MCPServerConfig,
        tool_name: str,
        description: Optional[str] = None,
    ) -> Tuple[RiskLevel, List[str]]:
        """
        Determine operational risk level and required capabilities for an MCP tool.
        Returns (RiskLevel, List[Capability]).
        """
        # 1. Explicit high-risk designation takes precedence
        if tool_name in server_config.high_risk_tools:
            return RiskLevel.HIGH, [Capability.MCP_EXECUTE.value]

        # 2. Check if tool contains mutation keywords
        name_lower = tool_name.lower()
        has_mutation_term = any(m in name_lower for m in self.MUTATION_KEYWORDS)

        # 3. Explicit auto-approve designation (only if no mutation terms exist)
        if tool_name in server_config.auto_approve_tools and not has_mutation_term:
            return RiskLevel.LOW, [Capability.MCP_READ.value]

        # 4. Server marked as strictly read-only
        if server_config.read_only and not has_mutation_term:
            if name_lower.startswith(self.READ_PREFIXES):
                return RiskLevel.LOW, [Capability.MCP_READ.value]
            return RiskLevel.MEDIUM, [Capability.MCP_READ.value]

        # 5. Conservative default: all external MCP tools require approval
        return RiskLevel.HIGH, [Capability.MCP_EXECUTE.value]


# Global security policy overlay instance
mcp_security_policy = MCPSecurityPolicy()
