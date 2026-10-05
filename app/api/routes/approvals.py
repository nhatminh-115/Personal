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
from app.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalResponse,
)
from app.api.pagination import decode_timestamp_id_cursor, set_next_cursor_header
from app.api.run_resume_lock import lock_run_resume
from app.approvals.service import ApprovalService
from app.core.errors import (
    ApprovalNotFoundError,
    MODEL_PROVIDER_FAILURE_MESSAGE,
    MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE,
    ProviderError,
)
from app.core.logging import logger
from app.db.models import DelegationModel, RunModel, RunStatus
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1/approvals", tags=["Approvals"])


def _get_active_interrupt(snapshot: Any) -> Optional[Dict[str, Any]]:
    """
    Extract the current active interrupt payload dictionary from a LangGraph StateSnapshot.
    Inspects snapshot.tasks for task.interrupts.
    """
    for task in getattr(snapshot, "tasks", ()):
        for intr in getattr(task, "interrupts", ()):
            val = getattr(intr, "value", intr)
            if isinstance(val, dict):
                return val
    return None


async def _record_parent_resume_failure(parent: RunModel, exc: Exception, trace_service: TraceService) -> None:
    provider_failure = isinstance(exc, ProviderError)
    if provider_failure:
        logger.error("Model provider failed while resuming parent run '%s'.", parent.id)
        parent.error_message = MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE
        parent.final_response = MODEL_PROVIDER_FAILURE_MESSAGE
        await trace_service.record_event(
            run_id=parent.id,
            session_id=parent.session_id,
            event_type="run_failed",
            payload={"error_category": "provider_failure"},
        )
    else:
        logger.error(
            "Error resuming parent graph: %s",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__) if exc.__traceback__ is not None else False,
        )
    parent.status = RunStatus.FAILED.value


@router.get("/pending", response_model=List[ApprovalResponse])
async def list_pending_approvals(
    response: Response,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int = Query(default=10, ge=1, le=25),
    approval_service: ApprovalService = Depends(get_approval_service),
) -> List[ApprovalResponse]:
    """Retrieve one bounded page of pending approvals requiring user decision."""
    cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor) if cursor is not None else (None, None)
    approval_rows = await approval_service.get_pending_approvals_page(
        after_created_at=cursor_created_at,
        after_id=cursor_id,
        limit=page_size + 1,
    )
    approvals = set_next_cursor_header(
        response, approval_rows, page_size,
        timestamp_for=lambda item: item.created_at,
        id_for=lambda item: item.id,
    )
    return [
        ApprovalResponse(
            id=a.id,
            run_id=a.run_id,
            session_id=a.session_id,
            tool_call_id=a.tool_call_id,
            tool_name=a.tool_name,
            tool_input=a.tool_input,
            risk_level=a.risk_level,
            status=a.status,
            decision_notes=a.decision_notes,
            created_at=a.created_at,
            decided_at=a.decided_at,
        )
        for a in approvals
    ]


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval_detail(
    approval_id: str,
    approval_service: ApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    """Retrieve details of a specific approval record."""
    try:
        a = await approval_service.get_approval(approval_id)
        return ApprovalResponse(
            id=a.id,
            run_id=a.run_id,
            session_id=a.session_id,
            tool_call_id=a.tool_call_id,
            tool_name=a.tool_name,
            tool_input=a.tool_input,
            risk_level=a.risk_level,
            status=a.status,
            decision_notes=a.decision_notes,
            created_at=a.created_at,
            decided_at=a.decided_at,
        )
    except ApprovalNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")


@router.post("/{approval_id}/decision", response_model=ApprovalDecisionResponse)
async def submit_approval_decision(
    approval_id: str,
    req: ApprovalDecisionRequest,
    db: AsyncSession = Depends(get_db),
    approval_service: ApprovalService = Depends(get_approval_service),
    mem_service: MemoryService = Depends(get_memory_service),
    trace_service: TraceService = Depends(get_trace_service),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    model_router: ModelRouter = Depends(get_model_router),
) -> ApprovalDecisionResponse:
    """
    Approve, reject, or edit a pending action.
    Binds decisions strictly to the ACTIVE LangGraph interrupt to prevent stale-approval reuse.
    Thread-safe and crash-safe against concurrent retries and system restarts.
    """
    try:
        approval = await approval_service.get_approval(approval_id)
    except ApprovalNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

    run_record = await trace_service.get_run(approval.run_id)
    if not run_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated run not found")

    # Serialize approval requests per run to avoid race conditions
    async with lock_run_resume(db, approval.run_id):
        # Re-fetch approval inside lock in case a concurrent request already updated its status
        approval = await approval_service.get_approval(approval_id)
        await db.refresh(run_record)
        if run_record.status in {
            RunStatus.COMPLETED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }:
            if approval.status == req.decision:
                return ApprovalDecisionResponse(
                    approval_id=approval_id,
                    status=approval.status,
                    run_id=run_record.id,
                    execution_status=run_record.status,
                    final_response=run_record.final_response,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Run has already reached terminal status '{run_record.status}'.",
            )

        graph = await get_compiled_graph()
        config = {
            "configurable": {
                "thread_id": approval.run_id,
                "db": db,
                "memory_service": mem_service,
                "approval_service": approval_service,
                "trace_service": trace_service,
                "tool_registry": tool_registry,
                "model_router": model_router,
            }
        }

        # Inspect current LangGraph thread execution state
        snapshot = await graph.aget_state(config)

        # 1. If graph has already completed on this thread
        if not snapshot.next:
            if approval.status != "pending":
                if req.decision != approval.status:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Approval has already been resolved with status '{approval.status}'.",
                    )
                # Already resolved and graph finished: return idempotent response
                return ApprovalDecisionResponse(
                    approval_id=approval_id,
                    status=approval.status,
                    run_id=run_record.id,
                    execution_status=run_record.status,
                    final_response=run_record.final_response,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Run has already completed and is no longer awaiting approval.",
                )

        # 2. Graph IS suspended at an interrupt
        active_intr = _get_active_interrupt(snapshot)
        active_approval_id = active_intr.get("approval_id") if active_intr else None
        active_tool_call_id = active_intr.get("tool_call_id") if active_intr else None

        # Verify whether the supplied approval corresponds strictly to the CURRENT interrupt
        is_current_interrupt = (
            active_intr is not None
            and active_approval_id == approval.id
            and active_tool_call_id == approval.tool_call_id
            and approval.run_id == run_record.id
        )

        if not is_current_interrupt:
            # Stale approval or mismatched approval submitted while another interrupt is active
            if approval.status != "pending":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Approval '{approval_id}' is stale and has already been resolved with status '{approval.status}'. "
                        f"Currently active approval is '{active_approval_id}'."
                    ),
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Approval '{approval_id}' is not the currently active interrupt. "
                        f"Currently active approval is '{active_approval_id}'."
                    ),
                )

        # 3. Supplied approval matches the ACTIVE interrupt
        if approval.status == "pending":
            # Normal first-time resolution: record decision in DB
            updated_approval = await approval_service.record_decision(
                approval_id=approval_id,
                decision=req.decision,
                decision_notes=req.decision_notes,
                edited_input=req.edited_input,
            )
            effective_decision = req.decision
            effective_notes = req.decision_notes
            effective_edited_input = req.edited_input
            current_status = updated_approval.status
        else:
            # Crash recovery: decision was already recorded in DB before process died,
            # but graph is still suspended at this exact interrupt
            if req.decision != approval.status:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Approval has already been resolved with status '{approval.status}'.",
                )
            logger.info(
                f"Reconciling pre-recorded approval decision '{approval.status}' for active interrupt '{approval_id}'",
                extra={"approval_id": approval_id, "run_id": approval.run_id},
            )
            effective_decision = approval.status
            effective_notes = approval.decision_notes
            effective_edited_input = approval.tool_input if approval.status == "edited" else req.edited_input
            current_status = approval.status

        resume_payload = {
            "decision": effective_decision,
            "decision_notes": effective_notes,
            "edited_input": effective_edited_input,
        }

        try:
            final_state = await graph.ainvoke(Command(resume=resume_payload), config=config)
        except Exception as exc:
            provider_failure = isinstance(exc, ProviderError)
            if provider_failure:
                logger.error("Model provider failed while resuming approved run '%s'.", run_record.id)
            else:
                logger.error(f"Graph execution failed during resume: {exc}", exc_info=True)
            run_record.status = RunStatus.FAILED.value
            run_record.error_message = MODEL_PROVIDER_FAILURE_STORAGE_MESSAGE if provider_failure else str(exc)

            failure_response = (
                MODEL_PROVIDER_FAILURE_MESSAGE
                if provider_failure
                else f"Run failed during execution: {exc}"
            )
            run_record.final_response = failure_response
            delegation = await db.scalar(
                select(DelegationModel).where(DelegationModel.child_run_id == run_record.id)
            )
            if delegation is not None:
                delegation.status = RunStatus.FAILED.value
                delegation.result_summary = failure_response
                delegation.pending_approval_id = None
            await db.commit()
            if trace_service:
                await trace_service.record_event(
                    run_id=approval.run_id,
                    session_id=approval.session_id,
                    event_type="run_failed",
                    payload={"error_category": "provider_failure" if provider_failure else "graph_failure"},
                )

            # A delegated child has its own durable graph thread. Once that thread
            # has failed it cannot resume the root's delegated tool call itself, so
            # deliver the terminal specialist result through the root's interrupt.
            if delegation is not None and getattr(run_record, "parent_run_id", None):
                parent = await trace_service.get_run(run_record.parent_run_id) if trace_service else None
                if parent is not None:
                    parent_config = {
                        "configurable": {
                            "thread_id": parent.id,
                            "db": db,
                            "memory_service": mem_service,
                            "approval_service": approval_service,
                            "trace_service": trace_service,
                            "tool_registry": tool_registry,
                            "model_router": model_router,
                        }
                    }
                    parent_snapshot = await graph.aget_state(parent_config)
                    parent_interrupt = _get_active_interrupt(parent_snapshot)
                    if (
                        parent_snapshot.next
                        and parent_interrupt is not None
                        and parent_interrupt.get("approval_id") == approval_id
                    ):
                        try:
                            parent_final = await graph.ainvoke(
                                Command(resume={
                                    "decision": effective_decision,
                                    "specialist_status": RunStatus.FAILED.value,
                                    "summary": failure_response,
                                }),
                                config=parent_config,
                            )
                            post_parent_snapshot = await graph.aget_state(parent_config)
                            if post_parent_snapshot.next:
                                parent.status = RunStatus.WAITING_FOR_APPROVAL.value
                            else:
                                parent.status = parent_final.get("execution_status", RunStatus.FAILED.value)
                                parent.final_response = parent_final.get("final_response")
                                parent.error_message = parent_final.get("error_message")
                        except Exception as parent_exc:
                            await _record_parent_resume_failure(parent, parent_exc, trace_service)
                    await db.commit()

            return ApprovalDecisionResponse(
                approval_id=approval_id,
                status=current_status,
                run_id=run_record.id,
                execution_status=RunStatus.FAILED.value,
                final_response=failure_response,
            )

        # Check if graph suspended at the NEXT interrupt (e.g. multi-tool approval)
        post_snapshot = await graph.aget_state(config)
        if post_snapshot.next:
            exec_status = RunStatus.WAITING_FOR_APPROVAL.value
            run_record.status = exec_status
            await db.commit()
            next_intr = _get_active_interrupt(post_snapshot)
            next_app_id = next_intr.get("approval_id") if next_intr else approval_id
            return ApprovalDecisionResponse(
                approval_id=next_app_id,
                status=current_status,
                run_id=run_record.id,
                execution_status=exec_status,
                final_response=None,
            )

        exec_status = final_state.get("execution_status", RunStatus.COMPLETED.value)
        final_response = final_state.get("final_response")

        run_record.status = exec_status
        run_record.final_response = final_response

        # Synchronize delegation record status
        del_stmt = select(DelegationModel).where(DelegationModel.child_run_id == run_record.id)
        del_res = await db.execute(del_stmt)
        delegation_entry = del_res.scalar_one_or_none()
        if delegation_entry:
            delegation_entry.status = exec_status
            delegation_entry.result_summary = final_response

        # Propagate completion to parent run if this was a delegated specialist run
        if getattr(run_record, "parent_run_id", None):
            parent = await trace_service.get_run(run_record.parent_run_id)
            if parent:
                parent_config = {
                    "configurable": {
                        "thread_id": parent.id,
                        "db": db,
                        "memory_service": mem_service,
                        "approval_service": approval_service,
                        "trace_service": trace_service,
                        "tool_registry": tool_registry,
                        "model_router": model_router,
                    }
                }
                parent_snapshot = await graph.aget_state(parent_config)
                if parent_snapshot.next:
                    try:
                        parent_final = await graph.ainvoke(
                            Command(resume={
                                "decision": effective_decision,
                                "specialist_status": exec_status,
                                "summary": final_response,
                            }),
                            config=parent_config,
                        )
                        parent.status = parent_final.get("execution_status", exec_status)
                        parent.final_response = parent_final.get("final_response") or f"Personal Orchestrator: Specialist completed task. {final_response}"
                    except Exception as parent_exc:
                        await _record_parent_resume_failure(parent, parent_exc, trace_service)
                else:
                    parent.status = exec_status
                    parent.final_response = f"Personal Orchestrator: Specialist completed task. {final_response}"
                    events = await trace_service.get_run_events(parent.id)
                    if not any(e.event_type == "delegation_completed" for e in events):
                        await trace_service.record_event(
                            run_id=parent.id,
                            session_id=parent.session_id,
                            event_type="delegation_completed",
                            payload={
                                "child_run_id": run_record.id,
                                "status": exec_status,
                                "summary": final_response,
                            },
                        )

        await db.commit()

        return ApprovalDecisionResponse(
            approval_id=approval_id,
            status=current_status,
            run_id=run_record.id,
            execution_status=exec_status,
            final_response=final_response,
        )

