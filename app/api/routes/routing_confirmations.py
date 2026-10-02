"""Durable ask-before-cloud routing confirmation lifecycle."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_approval_service,
    get_memory_service,
    get_model_router,
    get_tool_registry,
    get_trace_service,
)
from app.api.pagination import decode_timestamp_id_cursor, encode_timestamp_id_cursor, set_next_cursor_header
from app.api.schemas import (
    RoutingConfirmationDecisionRequest,
    RoutingConfirmationDecisionResponse,
    RoutingConfirmationResponse,
)
from app.approvals.service import ApprovalService
from app.core.logging import logger
from app.db.models import RunModel, RunStatus, RoutingConfirmationModel
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1/routing-confirmations", tags=["Routing Confirmations"])

_run_locks: Dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _get_run_lock(run_id: str) -> asyncio.Lock:
    async with _locks_guard:
        return _run_locks.setdefault(run_id, asyncio.Lock())


def _active_interrupt(snapshot: Any) -> Optional[Dict[str, Any]]:
    for task in getattr(snapshot, "tasks", ()):
        for interrupt_item in getattr(task, "interrupts", ()):
            value = getattr(interrupt_item, "value", interrupt_item)
            if isinstance(value, dict):
                return value
    return None


def _response(item: RoutingConfirmationModel) -> RoutingConfirmationResponse:
    return RoutingConfirmationResponse(
        id=item.id,
        root_run_id=item.root_run_id,
        execution_run_id=item.execution_run_id,
        session_id=item.session_id,
        proposed_provider=item.proposed_provider,
        proposed_model=item.proposed_model,
        status=item.status,
        decision_notes=item.decision_notes,
        created_at=item.created_at,
        decided_at=item.decided_at,
    )


def _graph_config(
    run_id: str,
    db: AsyncSession,
    mem_service: MemoryService,
    approval_service: ApprovalService,
    trace_service: TraceService,
    tool_registry: ToolRegistry,
    model_router: ModelRouter,
) -> dict[str, Any]:
    return {"configurable": {
        "thread_id": run_id,
        "db": db,
        "memory_service": mem_service,
        "approval_service": approval_service,
        "trace_service": trace_service,
        "tool_registry": tool_registry,
        "model_router": model_router,
    }}


@router.get("/pending", response_model=List[RoutingConfirmationResponse])
async def list_pending_routing_confirmations(
    response: Response,
    session_id: Optional[str] = Query(default=None, min_length=1, max_length=36),
    cursor: Optional[str] = Query(default=None, max_length=512),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> List[RoutingConfirmationResponse]:
    query = select(RoutingConfirmationModel).where(RoutingConfirmationModel.status == "pending")
    if session_id is not None:
        query = query.where(RoutingConfirmationModel.session_id == session_id)
    if cursor is not None:
        cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
        query = query.where(
            (RoutingConfirmationModel.created_at < cursor_created_at)
            | ((RoutingConfirmationModel.created_at == cursor_created_at) & (RoutingConfirmationModel.id < cursor_id))
        )
    result = await db.execute(
        query.order_by(RoutingConfirmationModel.created_at.desc(), RoutingConfirmationModel.id.desc()).limit(page_size + 1)
    )
    rows = list(result.scalars())
    items = set_next_cursor_header(
        response, rows, page_size,
        timestamp_for=lambda item: item.created_at,
        id_for=lambda item: item.id,
    )
    return [_response(item) for item in items]


@router.get("/{confirmation_id}", response_model=RoutingConfirmationResponse)
async def get_routing_confirmation(
    confirmation_id: str,
    db: AsyncSession = Depends(get_db),
) -> RoutingConfirmationResponse:
    item = await db.get(RoutingConfirmationModel, confirmation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Routing confirmation not found.")
    return _response(item)


@router.post(
    "/{confirmation_id}/decision",
    response_model=RoutingConfirmationDecisionResponse,
)
async def decide_routing_confirmation(
    confirmation_id: str,
    request: RoutingConfirmationDecisionRequest,
    db: AsyncSession = Depends(get_db),
    approval_service: ApprovalService = Depends(get_approval_service),
    mem_service: MemoryService = Depends(get_memory_service),
    trace_service: TraceService = Depends(get_trace_service),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    model_router: ModelRouter = Depends(get_model_router),
) -> RoutingConfirmationDecisionResponse:
    item = await db.get(RoutingConfirmationModel, confirmation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Routing confirmation not found.")

    lock = await _get_run_lock(item.root_run_id)
    async with lock:
        item = await db.get(RoutingConfirmationModel, confirmation_id)
        root_run = await db.get(RunModel, item.root_run_id) if item else None
        if item is None or root_run is None:
            raise HTTPException(status_code=404, detail="Routing confirmation run not found.")

        if item.status != "pending" and item.status != request.decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Routing confirmation was already resolved as '{item.status}'.",
            )

        graph = await get_compiled_graph()
        root_config = _graph_config(
            item.root_run_id, db, mem_service, approval_service, trace_service, tool_registry, model_router
        )
        root_snapshot = await graph.aget_state(root_config)
        active = _active_interrupt(root_snapshot)
        is_active = (
            active is not None
            and active.get("kind") == "routing_confirmation"
            and active.get("confirmation_id") == item.id
        )

        if not is_active:
            if item.status != "pending" and not root_snapshot.next:
                return RoutingConfirmationDecisionResponse(
                    confirmation_id=item.id,
                    status=item.status,
                    run_id=item.root_run_id,
                    execution_status=root_run.status,
                    final_response=root_run.final_response,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This routing confirmation is not the active decision for the run.",
            )

        if item.execution_run_id != item.root_run_id:
            execution_config = _graph_config(
                item.execution_run_id, db, mem_service, approval_service, trace_service, tool_registry, model_router
            )
            execution_snapshot = await graph.aget_state(execution_config)
            child_interrupt = _active_interrupt(execution_snapshot)
            if (
                child_interrupt is None
                or child_interrupt.get("kind") != "routing_confirmation"
                or child_interrupt.get("confirmation_id") != item.id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The specialist confirmation is no longer active.",
                )

        if item.status == "pending":
            item.status = request.decision
            item.decision_notes = request.decision_notes
            item.decided_at = datetime.now(timezone.utc)
            await db.commit()

        try:
            final_state = await graph.ainvoke(
                Command(resume={"confirmation_id": item.id, "decision": request.decision}),
                config=root_config,
            )
        except Exception as exc:
            logger.error("Graph failed while resolving routing confirmation.", exc_info=True)
            root_run.status = RunStatus.FAILED.value
            root_run.error_message = str(exc)
            await db.commit()
            await trace_service.record_event(
                run_id=root_run.id,
                session_id=root_run.session_id,
                event_type="run_failed",
                payload={"error": str(exc), "error_category": "routing_confirmation_resume"},
            )
            raise HTTPException(
                status_code=500,
                detail="The run failed while resuming after routing confirmation.",
            ) from exc

        post_snapshot = await graph.aget_state(root_config)
        if post_snapshot.next:
            next_interrupt = _active_interrupt(post_snapshot)
            if next_interrupt and next_interrupt.get("kind") == "routing_confirmation":
                root_run.status = RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value
                await db.commit()
                return RoutingConfirmationDecisionResponse(
                    confirmation_id=item.id,
                    status=item.status,
                    run_id=root_run.id,
                    execution_status=root_run.status,
                    next_routing_confirmation_id=next_interrupt.get("confirmation_id"),
                )
            root_run.status = RunStatus.WAITING_FOR_APPROVAL.value
            await db.commit()
            return RoutingConfirmationDecisionResponse(
                confirmation_id=item.id,
                status=item.status,
                run_id=root_run.id,
                execution_status=root_run.status,
                approval_id=(next_interrupt or {}).get("approval_id"),
            )

        root_run.status = final_state.get("execution_status", RunStatus.COMPLETED.value)
        root_run.final_response = final_state.get("final_response")
        root_run.error_message = final_state.get("error_message")
        await db.commit()
        await trace_service.record_event(
            run_id=root_run.id,
            session_id=root_run.session_id,
            event_type="routing_confirmation_decided",
            payload={
                "confirmation_id": item.id,
                "decision": item.status,
                "execution_run_id": item.execution_run_id,
            },
        )
        return RoutingConfirmationDecisionResponse(
            confirmation_id=item.id,
            status=item.status,
            run_id=root_run.id,
            execution_status=root_run.status,
            final_response=root_run.final_response,
        )
