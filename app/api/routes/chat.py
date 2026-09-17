"""Chat endpoint: POST /v1/chat."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_approval_service,
    get_memory_service,
    get_model_router,
    get_tool_registry,
    get_trace_service,
)
from app.api.schemas import ChatRequest, ChatResponse
from app.approvals.service import ApprovalService
from app.core.logging import logger
from app.db.models import RunModel
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import orchestrator_graph
from app.orchestrator.state import AgentState
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1", tags=["Chat"])


@router.post("/chat", response_model=ChatResponse, status_code=status.HTTP_200_OK)
async def chat_endpoint(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    mem_service: MemoryService = Depends(get_memory_service),
    approval_service: ApprovalService = Depends(get_approval_service),
    trace_service: TraceService = Depends(get_trace_service),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
    model_router: ModelRouter = Depends(get_model_router),
) -> ChatResponse:
    """
    Main entry point for agent interaction turn.
    """
    run_id = str(uuid.uuid4())

    # 1. Ensure session exists
    await mem_service.get_or_create_session(req.session_id)

    # 2. Persist Run entity in database
    run_record = RunModel(
        id=run_id,
        session_id=req.session_id,
        status="running",
        user_message=req.message,
    )
    db.add(run_record)
    await db.commit()

    # 3. Emit initial audit trace
    await trace_service.record_event(
        run_id=run_id,
        session_id=req.session_id,
        event_type="request_received",
        payload={"message": req.message},
    )

    # 4. Construct initial state for LangGraph
    initial_state: AgentState = {
        "run_id": run_id,
        "session_id": req.session_id,
        "user_message": req.message,
        "messages": [],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
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

    try:
        # 5. Invoke LangGraph orchestrator
        final_state: AgentState = await orchestrator_graph.ainvoke(initial_state, config=config)

        # 6. Update Run record
        run_record.status = final_state.get("execution_status", "completed")
        run_record.final_response = final_state.get("final_response")
        await db.commit()

        return ChatResponse(
            run_id=run_id,
            session_id=req.session_id,
            status=final_state.get("execution_status", "completed"),
            response=final_state.get("final_response"),
            approval_id=final_state.get("approval_id"),
            tool_results=final_state.get("tool_results", []),
        )

    except Exception as e:
        logger.error(f"Error executing run '{run_id}': {e}", exc_info=True)
        run_record.status = "failed"
        run_record.error_message = str(e)
        await db.commit()
        await trace_service.record_event(
            run_id=run_id,
            session_id=req.session_id,
            event_type="run_failed",
            payload={"error": str(e)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {str(e)}",
        )
