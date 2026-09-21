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
from app.db.models import RunModel, RunStatus
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.orchestrator.state import AgentState, create_initial_agent_state
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

    from app.models.routing_resolver import resolve_routing_profile, apply_routing_profile_to_context
    from app.models.base import RoutingContext

    profile, scope = await resolve_routing_profile(db, session_id=req.session_id, project_name=req.project_name)
    
    # Base routing context for Root
    root_context = RoutingContext(
        session_id=req.session_id,
        run_id=run_id
    )
    root_context = apply_routing_profile_to_context(
        profile,
        role="root",
        context=root_context,
        winning_scope=scope,
        message_override=req.model_override
    )

    # 2. Persist Run entity in database
    run_record = RunModel(
        id=run_id,
        session_id=req.session_id,
        status=RunStatus.RUNNING.value,
        user_message=req.message,
        routing_snapshot_json={
            "profile_id": profile.id,
            "profile_version": profile.version,
            "winning_scope": scope,
            "role": "root",
            "is_lock_all": root_context.is_lock_all,
            "privacy_policy": root_context.privacy_requirement.value,
            "fallback_policy": root_context.fallback_policy.value,
            "explicit_model_override": root_context.explicit_model_override,
            "reasoning_policy": root_context.reasoning_policy.value if root_context.reasoning_policy else None,
            "reasoning_effort": root_context.reasoning_effort.value if root_context.reasoning_effort else None,
        }
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
    
    await trace_service.record_event(
        run_id=run_id,
        session_id=req.session_id,
        event_type="routing_profile_resolved",
        payload=run_record.routing_snapshot_json,
    )

    # 4. Construct initial state for LangGraph
    merged_metadata = dict(req.metadata or {})
    merged_metadata["routing_context_dict"] = root_context.model_dump()
    merged_metadata["profile_id"] = profile.id
    merged_metadata["winning_scope"] = scope
    merged_metadata["is_lock_all"] = root_context.is_lock_all
    merged_metadata["global_fallback_policy"] = profile.global_fallback_policy.value
    
    if req.model_override:
        merged_metadata["model_override"] = req.model_override

    initial_state = create_initial_agent_state(
        run_id=run_id,
        session_id=req.session_id,
        user_message=req.message,
        project_name=req.project_name,
        metadata=merged_metadata,
    )

    config = {
        "configurable": {
            "thread_id": run_id,
            "db": db,
            "memory_service": mem_service,
            "approval_service": approval_service,
            "trace_service": trace_service,
            "tool_registry": tool_registry,
            "model_router": model_router,
        }
    }

    try:
        # 5. Invoke LangGraph orchestrator with durable checkpointer
        graph = await get_compiled_graph()
        result_state = await graph.ainvoke(initial_state, config=config)

        # 6. Check if execution was suspended via interrupt()
        if "__interrupt__" in result_state and len(result_state["__interrupt__"]) > 0:
            interrupt_val = result_state["__interrupt__"][0].value
            approval_id = interrupt_val.get("approval_id")
            tool_name = interrupt_val.get("tool_name")
            risk_level = interrupt_val.get("risk_level")

            run_record.status = RunStatus.WAITING_FOR_APPROVAL.value
            run_record.final_response = f"Action requires human approval: Tool '{tool_name}' has risk level '{risk_level}'. Approval ID: {approval_id}"
            await db.commit()

            return ChatResponse(
                run_id=run_id,
                session_id=req.session_id,
                status=RunStatus.WAITING_FOR_APPROVAL.value,
                response=run_record.final_response,
                approval_id=approval_id,
                tool_results=[],
            )

        # 7. Normal completion
        run_record.status = result_state.get("execution_status", RunStatus.COMPLETED.value)
        run_record.final_response = result_state.get("final_response")
        await db.commit()

        return ChatResponse(
            run_id=run_id,
            session_id=req.session_id,
            status=run_record.status,
            response=result_state.get("final_response"),
            approval_id=None,
            tool_results=result_state.get("tool_results", []),
        )

    except Exception as e:
        logger.error(f"Error executing run '{run_id}': {e}", exc_info=True)
        run_record.status = RunStatus.FAILED.value
        run_record.error_message = str(e)
        await db.commit()
        await trace_service.record_event(
            run_id=run_id,
            session_id=req.session_id,
            event_type="run_failed",
            payload={"error": str(e), "error_category": "graph_failure"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {str(e)}",
        )
