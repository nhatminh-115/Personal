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
from app.models.router import model_router
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.orchestrator.state import AgentState
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
        run_id = str(uuid.uuid4())

        logger.info(
            f"EventToAgentBridge triggering run '{run_id}' from event '{event.event_type}'",
            extra={"run_id": run_id, "session_id": session_id, "event_id": event.id},
        )

        async with self.session_factory() as db:
            mem_service = SQLMemoryService(db)
            approval_service = ApprovalService(db)
            trace_service = TraceService(db)

            await mem_service.get_or_create_session(session_id, title=f"Proactive: {event.event_type}")

            run_record = RunModel(
                id=run_id,
                session_id=session_id,
                status=RunStatus.RUNNING.value,
                user_message=message,
            )
            db.add(run_record)
            await db.commit()

            await trace_service.record_event(
                run_id=run_id,
                session_id=session_id,
                event_type="request_received",
                payload={"trigger_event_id": event.id, "message": message},
            )

            compiled_graph = await get_compiled_graph()
            initial_state: AgentState = {
                "run_id": run_id,
                "session_id": session_id,
                "user_message": message,
                "messages": [],
                "retrieved_context": [f"[Proactive Event Trigger]: {event.event_type} (source: {event.source})"],
                "current_plan": None,
                "tool_requests": [],
                "tool_results": [],
                "pending_approval": None,
                "approval_state": None,
                "final_response": None,
                "error": None,
                "execution_status": RunStatus.RUNNING.value,
                "metadata": payload.get("metadata", {}),
            }

            config = {
                "configurable": {
                    "thread_id": session_id,
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
                db_run.status = final_state.get("execution_status", RunStatus.COMPLETED.value)
                db_run.final_response = final_state.get("final_response")
                await db.commit()

            return final_state
