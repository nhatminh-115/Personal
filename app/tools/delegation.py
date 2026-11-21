"""DelegateTaskTool allowing the Personal Orchestrator to delegate to specialist agents."""

from typing import Any, Dict, List, Optional
from langgraph.errors import GraphInterrupt
from app.core.errors import (
    MODEL_PROVIDER_FAILURE_MESSAGE,
    PermissionError,
    ProviderError,
    ToolError,
)
from app.core.logging import logger
from app.delegation.types import DelegationRequest
from app.tools.base import RiskLevel, Tool, ToolResult

_DELEGATION_INTERNAL_FAILURE_MESSAGE = "Delegation failed because an internal error occurred."


class DelegateTaskTool(Tool):
    """Tool exposed to the Root Personal Orchestrator to invoke specialist agents."""

    def __init__(self, runtime: Optional[Any] = None) -> None:
        self._runtime = runtime

    @property
    def runtime(self) -> Any:
        if self._runtime is None:
            from app.delegation.runtime import delegation_runtime
            self._runtime = delegation_runtime
        return self._runtime

    @property
    def name(self) -> str:
        return "delegate_task"

    @property
    def description(self) -> str:
        return (
            "Delegate a scoped, specialized sub-task to an authorized specialist agent "
            "(e.g., 'coding' for inspecting code, running tests, diagnosing, and editing; "
            "'research' for literature review, finding prior art, reading paper methods, and extracting grounded evidence). "
            "Project scope and effective privacy/fallback policy are inherited from the active root run, not tool arguments. "
            "Only available to the Personal Orchestrator."
        )

    @property
    def required_capabilities(self) -> List[str]:
        from app.approvals.capabilities import Capability
        return [Capability.AGENT_DELEGATE.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "specialist_name": {
                    "type": "string",
                    "description": "Name of the target specialist (e.g. 'coding' or 'research').",
                },
                "task_description": {
                    "type": "string",
                    "description": "Scoped sub-task for the specialist; project scope and routing policy come from the runtime.",
                },
            },
            "required": ["specialist_name", "task_description"],
        }

    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Invoke specialist agent via delegation runtime."""
        specialist_name = input_data.get("specialist_name")
        task_description = input_data.get("task_description")
        if not specialist_name or not task_description:
            return ToolResult(
                success=False,
                output="",
                error="Parameters 'specialist_name' and 'task_description' are required.",
            )

        ctx = context or {}
        db = ctx.get("db")
        if not db:
            return ToolResult(
                success=False,
                output="",
                error="Database session required for delegation execution.",
            )

        # Model-generated tool arguments must never override routing or project scope.
        delegated_context = dict(ctx.get("metadata") or {})
        delegated_context["project_name"] = ctx.get("project_name")

        req = DelegationRequest(
            specialist_name=specialist_name,
            task_description=task_description,
            context=delegated_context,
            parent_run_id=ctx.get("run_id", "unknown-parent"),
            parent_tool_call_id=ctx.get("tool_call_id"),
            session_id=ctx.get("session_id", "unknown-session"),
        )

        try:
            result = await self.runtime.delegate(req, db=db, services=ctx.get("services"))
            success = result.status == "completed"
            return ToolResult(
                success=success,
                output=f"[{result.specialist_name.upper()} SPECIALIST - {result.status.upper()}]: {result.summary}",
                error=result.error if not success else None,
                metadata={
                    "specialist_name": result.specialist_name,
                    "child_run_id": result.child_run_id,
                    "status": result.status,
                    "steps_taken": result.steps_taken,
                },
            )
        except GraphInterrupt:
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            if isinstance(exc, ProviderError):
                error_message = MODEL_PROVIDER_FAILURE_MESSAGE
                error_category = "provider_failure"
            elif isinstance(exc, (ToolError, PermissionError)):
                # These errors are raised by preflight validation with actionable,
                # application-authored messages before a child run is started.
                error_message = exc.message
                error_category = "delegation_rejected"
            else:
                error_message = _DELEGATION_INTERNAL_FAILURE_MESSAGE
                error_category = "internal_error"
            logger.error(
                "Delegation failed before a result was returned.",
                extra={
                    "run_id": ctx.get("run_id"),
                    "details": {
                        "error_category": error_category,
                        "exception_type": error_type,
                    },
                },
            )
            return ToolResult(
                success=False,
                output="",
                error=error_message,
                metadata={
                    "specialist_name": specialist_name,
                    "error_category": error_category,
                    "error_type": error_type,
                },
            )

