"""Approvals endpoints: GET/POST /v1/approvals."""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
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
from app.db.models import RunModel
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import resume_execution
from app.orchestrator.state import AgentState
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
    If approved, resumes execution to complete the paused run.
    """
    try:
        approval = await approval_service.get_approval(approval_id)
    except ApprovalNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")

    if approval.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval has already been resolved with status '{approval.status}'.",
        )

    # Record user decision in DB
    updated_approval = await approval_service.record_decision(
        approval_id=approval_id,
        decision=req.decision,
        decision_notes=req.decision_notes,
        edited_input=req.edited_input,
    )

    # Fetch associated run record
    run_record = await trace_service.get_run(updated_approval.run_id)
    if not run_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated run not found")

    if req.decision == "rejected":
        run_record.status = "completed"
        run_record.final_response = "Action was rejected by the user. Tool execution cancelled."
        await db.commit()

        await trace_service.record_event(
            run_id=run_record.id,
            session_id=run_record.session_id,
            event_type="approval_rejected",
            payload={"approval_id": approval_id, "notes": req.decision_notes},
        )

        return ApprovalDecisionResponse(
            approval_id=approval_id,
            status="rejected",
            run_id=run_record.id,
            execution_status="completed",
            final_response=run_record.final_response,
        )

    # If approved or edited: resume execution
    tool_input_to_run = req.edited_input if req.decision == "edited" and req.edited_input else updated_approval.tool_input

    resumed_state: AgentState = {
        "run_id": run_record.id,
        "session_id": run_record.session_id,
        "user_message": run_record.user_message,
        "messages": [{"role": "user", "content": run_record.user_message}],
        "retrieved_context": [],
        "current_plan": f"Resumed execution of approved tool: {updated_approval.tool_name}",
        "tool_requests": [
            {
                "id": f"approved_{approval_id[:8]}",
                "name": updated_approval.tool_name,
                "arguments": tool_input_to_run,
            }
        ],
        "tool_results": [],
        "approval_id": approval_id,
        "approval_state": "approved",
        "execution_status": "running",
        "errors": [],
        "final_response": None,
    }

    config = {
        "configurable": {
            "memory_service": mem_service,
            "approval_service": approval_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": model_router,
        }
    }

    await trace_service.record_event(
        run_id=run_record.id,
        session_id=run_record.session_id,
        event_type="approval_granted",
        payload={"approval_id": approval_id, "tool_name": updated_approval.tool_name},
    )

    final_state = await resume_execution(resumed_state, config)

    run_record.status = final_state.get("execution_status", "completed")
    run_record.final_response = final_state.get("final_response")
    await db.commit()

    return ApprovalDecisionResponse(
        approval_id=approval_id,
        status=updated_approval.status,
        run_id=run_record.id,
        execution_status=run_record.status,
        final_response=run_record.final_response,
    )
