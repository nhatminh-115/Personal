"""DelegateTaskTool allowing the Personal Orchestrator to delegate to specialist agents."""

from typing import Any, Dict, List, Optional
from langgraph.errors import GraphInterrupt
from app.delegation.types import DelegationRequest
from app.tools.base import RiskLevel, Tool, ToolResult


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
            "(e.g., 'coding' for inspecting code, running tests, diagnosing, and editing). "
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
                    "description": "Name of the target specialist (e.g. 'coding').",
                },
                "task_description": {
                    "type": "string",
                    "description": "Detailed description of the task for the specialist.",
                },
                "context": {
                    "type": "object",
                    "description": "Optional additional task parameters or project metadata.",
                    "default": {},
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
        extra_ctx = input_data.get("context") or {}

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

        req = DelegationRequest(
            specialist_name=specialist_name,
            task_description=task_description,
            context=extra_ctx,
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
            return ToolResult(
                success=False,
                output="",
                error=f"Delegation failed: {exc}",
                metadata={"specialist_name": specialist_name},
            )
