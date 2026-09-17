"""Adapter exposing MCP tools as canonical AURA Tool instances."""

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from app.core.logging import logger
from app.mcp.policy import MCPSecurityPolicy, MCPValidationError, mcp_security_policy
from app.tools.base import RiskLevel, Tool, ToolResult

if TYPE_CHECKING:
    from app.mcp.manager import MCPClientManager


class MCPToolAdapter(Tool):
    """
    Wraps an external MCP tool definition and delegates execution
    to the MCPClientManager with local schema validation and policy governance.
    """

    def __init__(
        self,
        server_id: str,
        mcp_tool_name: str,
        description: str,
        input_schema: Dict[str, Any],
        risk_level: RiskLevel,
        required_capabilities: List[str],
        manager: "MCPClientManager",
        policy: Optional[MCPSecurityPolicy] = None,
    ) -> None:
        self._server_id = server_id
        self._mcp_tool_name = mcp_tool_name
        self._description = description
        self._parameters_schema = input_schema
        self._risk_level = risk_level
        self._required_capabilities = required_capabilities
        self._manager = manager
        self._policy = policy or mcp_security_policy

        # Canonical name in AURA namespace: mcp_{server_id}_{tool_name}
        self._name = f"mcp_{server_id}_{mcp_tool_name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def mcp_tool_name(self) -> str:
        return self._mcp_tool_name

    @property
    def description(self) -> str:
        return self._description or f"MCP tool '{self._mcp_tool_name}' on server '{self._server_id}'."

    @property
    def required_capabilities(self) -> List[str]:
        return self._required_capabilities

    @property
    def risk_level(self) -> RiskLevel:
        return self._risk_level

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return self._parameters_schema

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        """Execute the MCP tool via client manager with input validation and crash isolation."""
        # 1. Enforce local schema validation overlay
        try:
            self._policy.validate_arguments(
                tool_name=self._name,
                input_schema=self._parameters_schema,
                arguments=input_data,
            )
        except MCPValidationError as val_err:
            logger.warning(f"MCP tool '{self._name}' rejected: {val_err}")
            return ToolResult(
                success=False,
                output="",
                error=str(val_err),
                metadata={"error_category": "validation_error", "server_id": self._server_id},
            )

        # 2. Delegate execution to MCP manager with server-level failure isolation
        try:
            result = await self._manager.call_tool(
                server_id=self._server_id,
                tool_name=self._mcp_tool_name,
                arguments=input_data,
            )
            return result
        except Exception as e:
            logger.error(f"Error executing MCP tool '{self._name}': {e}", exc_info=True)
            return ToolResult(
                success=False,
                output="",
                error=f"MCP invocation failure on server '{self._server_id}': {str(e)}",
                metadata={"error_category": "mcp_execution_failure", "server_id": self._server_id},
            )
