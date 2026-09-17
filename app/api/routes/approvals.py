"""Approvals endpoints: GET/POST /v1/approvals."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.types import Command
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
from app.approvals.service import ApprovalService
from app.core.errors import ApprovalNotFoundError
from app.core.logging import logger
from app.db.models import RunModel, RunStatus
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1/approvals", tags=["Approvals"])


@router.get("/pending", response_model=List[ApprovalResponse])
async def list_pending_approvals(
    approval_service: ApprovalService = Depends(get_approval_service),
) -> List[ApprovalResponse]:
    """Retrieve all pending approvals requiring user decision."""
    approvals = await approval_service.get_pending_approvals()
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
    Idempotent and crash-safe: reconciles DB approval state with LangGraph thread snapshot.
    """
    try:
        approval = await approval_service.get_approval(approval_id)
    except ApprovalNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

    run_record = await trace_service.get_run(approval.run_id)
    if not run_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated run not found")

    graph = await get_compiled_graph()
    config = {
        "configurable": {
            "thread_id": approval.run_id,
            "memory_service": mem_service,
            "approval_service": approval_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": model_router,
        }
    }

    # Inspect current LangGraph thread execution state
    snapshot = await graph.aget_state(config)

    # If graph has already completed on this thread
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

    # Graph is still suspended at an interrupt
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
        # Crash recovery / retry: decision was already recorded in DB before process died
        logger.info(
            f"Reconciling pre-recorded approval decision '{approval.status}' for approval '{approval_id}'",
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
        logger.error(f"Graph execution failed during resume: {exc}", exc_info=True)
        run_record.status = RunStatus.FAILED.value
        await db.commit()
        if trace_service:
            err_category = "provider_failure" if "provider" in type(exc).__name__.lower() else "graph_failure"
            await trace_service.record_event(
                run_id=approval.run_id,
                session_id=approval.session_id,
                event_type="run_failed",
                payload={"error": str(exc), "error_category": err_category},
            )
        return ApprovalDecisionResponse(
            approval_id=approval_id,
            status=current_status,
            run_id=run_record.id,
            execution_status=RunStatus.FAILED.value,
            final_response=f"Run failed during execution: {exc}",
        )

    # Check if graph suspended at another interrupt (e.g. multi-tool approval)
    post_snapshot = await graph.aget_state(config)
    if post_snapshot.next:
        exec_status = RunStatus.WAITING_FOR_APPROVAL.value
        run_record.status = exec_status
        await db.commit()
        next_app = await approval_service.get_approval_by_run(approval.run_id)
        return ApprovalDecisionResponse(
            approval_id=next_app.id if next_app else approval_id,
            status=current_status,
            run_id=run_record.id,
            execution_status=exec_status,
            final_response=None,
        )

    exec_status = final_state.get("execution_status", RunStatus.COMPLETED.value)
    final_response = final_state.get("final_response")

    run_record.status = exec_status
    run_record.final_response = final_response
    await db.commit()

    return ApprovalDecisionResponse(
        approval_id=approval_id,
        status=current_status,
        run_id=run_record.id,
        execution_status=exec_status,
        final_response=final_response,
    )
