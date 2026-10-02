"""Event-to-Agent bridge dispatching proactive event triggers to the Personal Orchestrator."""

import uuid
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.service import ApprovalService
from app.core.logging import logger
from app.db.models import RunModel, RunStatus, ScheduledJobModel, SessionModel
from app.db.session import async_session_factory
from app.models.base import FallbackPolicy, PrivacyPolicy, RoutingContext
from app.models.routing_resolver import apply_routing_profile_to_context, resolve_routing_profile
from app.events.types import AURAEvent
from app.memory.service import SQLMemoryService
from app.models.router import model_router
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
        # Outbox delivery is at-least-once. Tie the orchestration run to the
        # event so a retry after a process restart cannot create duplicate runs.
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))
        project_name = payload.get("project_name")

        logger.info(
            f"EventToAgentBridge triggering run '{run_id}' from event '{event.event_type}'",
            extra={"run_id": run_id, "session_id": session_id, "event_id": event.id},
        )

        async with self.session_factory() as db:
            existing_run = await db.get(RunModel, run_id)
            if existing_run is not None:
                logger.info(
                    "Skipping duplicate event delivery for an existing run",
                    extra={"run_id": run_id, "event_id": event.id},
                )
                return {"run_id": run_id, "execution_status": existing_run.status}

            mem_service = SQLMemoryService(db)
            approval_service = ApprovalService(db)
            trace_service = TraceService(db)

            await mem_service.get_or_create_session(session_id, title=f"Proactive: {event.event_type}")
            session_record = await db.get(SessionModel, session_id)
            if session_record:
                if project_name and not session_record.project_name:
                    session_record.project_name = project_name
                project_name = session_record.project_name or project_name

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
            raw_automation_id = payload.get("automation_id")
            automation_record = (
                await db.get(ScheduledJobModel, raw_automation_id)
                if isinstance(raw_automation_id, str) and raw_automation_id
                else None
            )
            automation_metadata = (
                automation_record.metadata_json if automation_record and isinstance(automation_record.metadata_json, dict) else {}
            )
            is_automation = automation_metadata.get("kind") == "automation"
            automation_id = automation_record.id if is_automation and automation_record else None
            automation_name = (
                automation_record.name[:128]
                if is_automation and automation_record and isinstance(automation_record.name, str)
                else None
            )
            if is_automation:
                # Scheduled/manual automation turns are always local-only,
                # even when an assigned profile allows cloud routing.
                routing_context.privacy_requirement = PrivacyPolicy.LOCAL_ONLY
                routing_context.fallback_policy = FallbackPolicy.LOCAL_ONLY
            routing_context_dict = routing_context.model_dump(mode="json")
            routing_snapshot = {
                "profile_id": profile.id,
                "profile_version": profile.version,
                "winning_scope": routing_context.winning_scope,
                "role": "root",
                "is_lock_all": routing_context.is_lock_all,
                "privacy_policy": routing_context.privacy_requirement.value,
                "fallback_policy": routing_context.fallback_policy.value,
                "explicit_model_override": routing_context.explicit_model_override,
                "reasoning_policy": routing_context.reasoning_policy.value if routing_context.reasoning_policy else None,
                "reasoning_effort": routing_context.reasoning_effort.value if routing_context.reasoning_effort else None,
            }
            run_metadata = dict(payload.get("metadata") or {})
            run_metadata["routing_context_dict"] = routing_context_dict
            run_metadata["routing_profile_id"] = profile.id
            run_metadata["routing_profile_version"] = profile.version
            run_metadata["winning_scope"] = routing_context.winning_scope

            run_record = RunModel(
                id=run_id,
                session_id=session_id,
                status=RunStatus.RUNNING.value,
                user_message=message,
                routing_snapshot_json=routing_snapshot,
            )
            db.add(run_record)
            await db.commit()

            await trace_service.record_event(
                run_id=run_id,
                session_id=session_id,
                event_type="routing_profile_resolved",
                payload=routing_snapshot,
            )
            if automation_id:
                await trace_service.record_event(
                    run_id=run_id,
                    session_id=session_id,
                    event_type="automation_triggered",
                    payload={
                        "trigger_event_id": event.id,
                        "automation_id": automation_id,
                        "automation_name": automation_name,
                    },
                )
            await trace_service.record_event(
                run_id=run_id,
                session_id=session_id,
                event_type="request_received",
                payload={"trigger_event_id": event.id, "message": message},
            )

            compiled_graph = await get_compiled_graph()
            initial_state = create_initial_agent_state(
                run_id=run_id,
                session_id=session_id,
                user_message=message,
                project_name=project_name,
                metadata=run_metadata,
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

            final_state = await compiled_graph.ainvoke(initial_state, config=config)

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
