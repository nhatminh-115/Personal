"""Event-to-Agent bridge dispatching proactive event triggers to the Personal Orchestrator."""

import uuid
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import ApprovalService
from app.core.logging import logger
from app.db.models import RunModel, RunStatus
from app.db.session import async_session_factory
from app.events.types import AURAEvent
from app.memory.service import SQLMemoryService
from app.models.base import FallbackPolicy, PrivacyPolicy, RoutingContext
from app.models.router import model_router
from app.models.routing_resolver import apply_routing_profile_to_context, resolve_routing_profile
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.orchestrator.state import AgentState, create_initial_agent_state
from app.tools.registry import tool_registry


class EventToAgentBridge:
    """
    Subscribes to proactive events (timers, cron ticks, external webhooks)
    and bridges them deterministically into the Personal Orchestrator graph.
    """

    def __init__(self, session_factory=None) -> None:
        self.session_factory = session_factory or async_session_factory

    async def handle_event(self, event: AURAEvent) -> Optional[Dict[str, Any]]:
        """Process an event by triggering an agent turn if payload indicates an agent action."""
        payload = event.payload or {}
        message = payload.get("message") or payload.get("instruction")

        if not message:
            logger.debug(f"Event '{event.event_type}' [{event.id}] has no actionable message. Skipping agent invocation.")
            return None

        session_id = payload.get("session_id") or f"proactive-{event.event_type.replace('.', '-')}"
        # The outbox can redeliver after a worker restart. A stable run identity
        # prevents the same event from executing side effects twice.
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))
        project_name = payload.get("project_name")

        logger.info(
            f"EventToAgentBridge triggering run '{run_id}' from event '{event.event_type}'",
            extra={"run_id": run_id, "session_id": session_id, "event_id": event.id},
        )

        async with self.session_factory() as db:
            existing_run = await db.get(RunModel, run_id)
            if existing_run is not None:
                return {
                    "run_id": existing_run.id,
                    "execution_status": existing_run.status,
                    "final_response": existing_run.final_response,
                    "deduplicated": True,
                }

            mem_service = SQLMemoryService(db)
            approval_service = ApprovalService(db)
            trace_service = TraceService(db)

            await mem_service.get_or_create_session(session_id, title=f"Proactive: {event.event_type}")
            if project_name:
                await mem_service.attach_session_to_project(session_id, project_name)

            profile, winning_scope = await resolve_routing_profile(
                db,
                session_id=session_id,
                project_name=project_name,
            )
            routing_context = apply_routing_profile_to_context(
                profile,
                role="root",
                context=RoutingContext(session_id=session_id, run_id=run_id),
                winning_scope=winning_scope,
            )
            metadata = dict(payload.get("metadata") or {})
            if metadata.get("force_local_only") is True or payload.get("automation_id"):
                # Scheduled routines cannot pause for a pre-run cloud-routing
                # confirmation. Keep every scheduled turn local-only; tool
                # side effects remain subject to the normal approval policy.
                routing_context.privacy_requirement = PrivacyPolicy.LOCAL_ONLY
                routing_context.fallback_policy = FallbackPolicy.LOCAL_ONLY
            metadata.update({
                "routing_context_dict": routing_context.model_dump(mode="json"),
                "profile_id": profile.id,
                "winning_scope": routing_context.winning_scope,
                "is_lock_all": routing_context.is_lock_all,
                "global_fallback_policy": routing_context.fallback_policy.value,
                "automation_id": payload.get("automation_id"),
                "trigger_event_id": event.id,
            })

            run_record = RunModel(
                id=run_id,
                session_id=session_id,
                status=RunStatus.RUNNING.value,
                user_message=message,
                routing_snapshot_json={
                    "profile_id": profile.id,
                    "profile_version": profile.version,
                    "winning_scope": routing_context.winning_scope,
                    "role": "root",
                    "privacy_policy": routing_context.privacy_requirement.value,
                    "fallback_policy": routing_context.fallback_policy.value,
                    "explicit_model_override": routing_context.explicit_model_override,
                    "reasoning_policy": routing_context.reasoning_policy.value if routing_context.reasoning_policy else None,
                    "reasoning_effort": routing_context.reasoning_effort.value if routing_context.reasoning_effort else None,
                    "trigger_event_id": event.id,
                    "automation_id": payload.get("automation_id"),
                    "routing_context": routing_context.model_dump(mode="json"),
                },
            )
            db.add(run_record)
            await db.commit()

            await trace_service.record_event(
                run_id=run_id,
                session_id=session_id,
                event_type="request_received",
                payload={"trigger_event_id": event.id, "message": message},
            )
            await trace_service.record_event(
                run_id=run_id,
                session_id=session_id,
                event_type="routing_profile_resolved",
                payload=run_record.routing_snapshot_json,
            )

            compiled_graph = await get_compiled_graph()
            initial_state = create_initial_agent_state(
                run_id=run_id,
                session_id=session_id,
                user_message=message,
                project_name=project_name,
                metadata=metadata,
            )
            initial_state["retrieved_context"] = [
                f"[Proactive Event Trigger]: {event.event_type} (source: {event.source})"
            ]

            config = {
                "configurable": {
                    "thread_id": run_id,
                    "memory_service": mem_service,
                    "approval_service": approval_service,
                    "trace_service": trace_service,
                    "tool_registry": tool_registry,
                    "model_router": model_router,
                }
            }

            try:
                final_state = await compiled_graph.ainvoke(initial_state, config=config)
            except Exception as exc:
                db_run = await db.get(RunModel, run_id)
                if db_run:
                    db_run.status = RunStatus.FAILED.value
                    db_run.error_message = str(exc)[:2_000]
                    await db.commit()
                logger.exception(
                    "Proactive agent run failed",
                    extra={"run_id": run_id, "event_id": event.id},
                )
                return {"run_id": run_id, "execution_status": RunStatus.FAILED.value}

            # Update run record in DB
            db_run = await db.get(RunModel, run_id)
            if db_run:
                if "__interrupt__" in final_state and len(final_state["__interrupt__"]) > 0:
                    interrupt_val = final_state["__interrupt__"][0].value
                    approval_id = interrupt_val.get("approval_id")
                    tool_name = interrupt_val.get("tool_name")
                    risk_level = interrupt_val.get("risk_level")
                    db_run.status = RunStatus.WAITING_FOR_APPROVAL.value
                    db_run.final_response = f"Action requires human approval: Tool '{tool_name}' has risk level '{risk_level}'. Approval ID: {approval_id}"
                else:
                    db_run.status = final_state.get("execution_status", RunStatus.COMPLETED.value)
                    db_run.final_response = final_state.get("final_response")
                await db.commit()

            return final_state
