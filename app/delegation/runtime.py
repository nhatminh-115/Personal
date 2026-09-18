"""Runtime orchestrating execution of delegated specialist tasks."""

import time
import uuid
from typing import Any, Dict, Optional
from langgraph.errors import GraphInterrupt
from langgraph.types import Command, interrupt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionError, ToolError
from app.core.logging import logger
from app.db.models import RunModel, RunStatus
from app.delegation.registry import SpecialistRegistry, specialist_registry
from app.delegation.types import DelegationRequest, DelegationResult, SpecialistDefinition
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.orchestrator.state import AgentState
from app.tools.registry import ToolRegistry, tool_registry
from app.tools.scoped import ScopedToolRegistry


class DelegationRuntime:
    """Manages the lifecycle of specialist child runs delegated by the Root Orchestrator."""

    def __init__(
        self,
        registry: Optional[SpecialistRegistry] = None,
        base_tool_registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.registry = registry or specialist_registry
        self.base_tool_registry = base_tool_registry or tool_registry

    async def delegate(
        self,
        request: DelegationRequest,
        db: AsyncSession,
        services: Optional[Dict[str, Any]] = None,
    ) -> DelegationResult:
        """Execute a specialized sub-task in an isolated, scoped child run."""
        # 1. Lookup specialist definition
        spec = self.registry.get(request.specialist_name)
        if not spec:
            raise ToolError(f"Specialist '{request.specialist_name}' is not registered.")

        # 2. Prevent infinite recursion or unconstrained specialist->specialist swarms
        if request.context.get("is_specialist"):
            raise PermissionError(
                f"Delegation rejected: Agent '{request.context.get('specialist_name', 'specialist')}' "
                "is already a specialist and cannot delegate to other specialists."
            )

        child_run_id = str(uuid.uuid4())
        trace_service = services.get("trace_service") if services else TraceService(db)

        # 3. Create Child Run record in DB with parent lineage
        child_run = RunModel(
            id=child_run_id,
            session_id=request.session_id,
            user_message=f"[Specialist: {spec.name}] {request.task_description}",
            parent_run_id=request.parent_run_id,
            status=RunStatus.RUNNING.value,
        )
        db.add(child_run)
        await db.commit()

        # 4. Trace delegation start
        if trace_service:
            await trace_service.record_event(
                run_id=request.parent_run_id,
                session_id=request.session_id,
                event_type="delegation_started",
                payload={
                    "specialist": spec.name,
                    "child_run_id": child_run_id,
                    "task": request.task_description,
                },
            )
            await trace_service.record_event(
                run_id=child_run_id,
                session_id=request.session_id,
                event_type="request_received",
                payload={
                    "parent_run_id": request.parent_run_id,
                    "specialist": spec.name,
                    "task": request.task_description,
                },
            )

        # 5. Build Scoped Tool Registry for the specialist
        scoped_tools = ScopedToolRegistry(self.base_tool_registry, spec.allowed_tools)

        # 6. Prepare Child Initial AgentState
        from app.models.base import ChatMessage, ModelRole

        initial_state: AgentState = {
            "session_id": request.session_id,
            "run_id": child_run_id,
            "user_message": request.task_description,
            "retrieved_context": [],
            "messages": [
                ChatMessage(role=ModelRole.SYSTEM, content=spec.system_prompt_template).model_dump(),
                ChatMessage(role=ModelRole.USER, content=request.task_description).model_dump(),
            ],
            "step_number": 0,
            "max_steps": request.max_steps or spec.max_steps,
            "total_tool_calls": 0,
            "max_tool_calls": 25,
            "consecutive_failures": 0,
            "max_consecutive_failures": 3,
            "deadline_seconds": (time.time() + float(request.timeout_seconds or spec.timeout_seconds)) if (request.timeout_seconds or spec.timeout_seconds) else None,
            "start_time": time.time(),
            "delegation_context": {
                "is_specialist": True,
                "specialist_name": spec.name,
                "parent_run_id": request.parent_run_id,
                "task_type": spec.name,
                "auto_approve_tools": spec.auto_approve_tools,
            },
            "metadata": {
                "task_type": spec.name,
                "required_capabilities": spec.preferred_model_capabilities,
                **(request.context or {}),
            },
            "project_name": request.context.get("project_name") if request.context else None,
        }

        # 7. Execute compiled graph with injected scoped registry
        graph = await get_compiled_graph()
        child_config = {
            "configurable": {
                "thread_id": child_run_id,
                "db": db,
                "tool_registry": scoped_tools,
                "memory_service": services.get("memory_service") if services else None,
                "approval_service": services.get("approval_service") if services else None,
                "trace_service": trace_service,
                "model_router": services.get("model_router") if services else None,
            }
        }

        try:
            final_state = await graph.ainvoke(initial_state, config=child_config)

            # Check if child graph was suspended for human approval
            if "__interrupt__" in final_state and len(final_state["__interrupt__"]) > 0:
                interrupt_val = final_state["__interrupt__"][0].value
                approval_id = interrupt_val.get("approval_id")
                tool_name = interrupt_val.get("tool_name")
                risk_level = interrupt_val.get("risk_level")

                child_run.status = RunStatus.WAITING_FOR_APPROVAL.value
                child_run.final_response = f"Specialist requires approval for '{tool_name}' ({risk_level}). Approval ID: {approval_id}"
                await db.commit()

                # Bubble up interrupt to parent Personal Orchestrator
                parent_resume = interrupt({
                    "approval_id": approval_id,
                    "tool_name": tool_name,
                    "risk_level": risk_level,
                    "specialist_name": spec.name,
                    "child_run_id": child_run_id,
                })

                # Resume child graph with decision
                final_state = await graph.ainvoke(Command(resume=parent_resume), config=child_config)

            status = final_state.get("execution_status", "completed")
            summary = final_state.get("final_response") or "Specialist execution finished."
            error = final_state.get("error_message") or final_state.get("termination_reason")
            steps = final_state.get("step_number", 0)

            # Update child run in database
            child_run.status = status
            child_run.final_response = summary
            child_run.error_message = error
            await db.commit()

            if trace_service:
                await trace_service.record_event(
                    run_id=request.parent_run_id,
                    session_id=request.session_id,
                    event_type="delegation_completed",
                    payload={
                        "child_run_id": child_run_id,
                        "specialist": spec.name,
                        "status": status,
                        "summary": summary,
                        "steps": steps,
                    },
                )

            return DelegationResult(
                specialist_name=spec.name,
                child_run_id=child_run_id,
                status=status,
                summary=summary,
                steps_taken=steps,
                error=error,
            )

        except GraphInterrupt:
            raise
        except Exception as exc:
            logger.error(f"Specialist child run '{child_run_id}' failed: {exc}", exc_info=True)
            child_run.status = RunStatus.FAILED.value
            child_run.error_message = str(exc)
            await db.commit()

            if trace_service:
                await trace_service.record_event(
                    run_id=request.parent_run_id,
                    session_id=request.session_id,
                    event_type="delegation_failed",
                    payload={
                        "child_run_id": child_run_id,
                        "specialist": spec.name,
                        "error": str(exc),
                    },
                )

            return DelegationResult(
                specialist_name=spec.name,
                child_run_id=child_run_id,
                status="failed",
                summary="Specialist failed due to an execution error.",
                steps_taken=0,
                error=str(exc),
            )


# Global singleton runtime
delegation_runtime = DelegationRuntime()
