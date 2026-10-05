"""Chat endpoint: POST /v1/chat."""

import hashlib
import json
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
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
from app.db.models import (
    ApprovalModel,
    MessageModel,
    RoutingConfirmationModel,
    RunModel,
    RunStatus,
    WorkspaceObjectModel,
    WorkspaceObjectProjectLinkModel,
    utc_now,
)
from app.db.session import get_db
from app.memory.base import MemoryService
from app.models.router import ModelRouter
from app.core.errors import (
    AuraError,
    ContextSelectionError,
    ModelCapabilityMismatch,
    ModelUnavailable,
    NoEligibleRoute,
    PrivacyBoundaryViolation,
    ReasoningControlUnsupported,
    RoutingConfirmationRequired,
)
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.orchestrator.state import AgentState, create_initial_agent_state
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1", tags=["Chat"])


def _chat_request_fingerprint(req: ChatRequest) -> str:
    payload = req.model_dump(mode="json", exclude={"client_turn_id"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _existing_chat_response(
    db: AsyncSession,
    run: RunModel,
    *,
    request_fingerprint: str,
) -> ChatResponse:
    if run.request_fingerprint != request_fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ChatTurnIdConflict",
                "message": "This client turn ID is already bound to a different chat request.",
            },
        )

    message_result = await db.execute(
        select(MessageModel.role, MessageModel.id).where(
            MessageModel.session_id == run.session_id,
            MessageModel.metadata_json["run_id"].as_string() == run.id,
        )
    )
    message_ids = {role: message_id for role, message_id in message_result.all()}

    approval_id = None
    if run.status == RunStatus.WAITING_FOR_APPROVAL.value:
        child_run_ids = select(RunModel.id).where(
            or_(RunModel.id == run.id, RunModel.parent_run_id == run.id)
        )
        approval_id = await db.scalar(
            select(ApprovalModel.id)
            .where(
                ApprovalModel.run_id.in_(child_run_ids),
                ApprovalModel.status == "pending",
            )
            .order_by(ApprovalModel.created_at.desc(), ApprovalModel.id.desc())
            .limit(1)
        )

    confirmation = None
    if run.status == RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value:
        confirmation = await db.scalar(
            select(RoutingConfirmationModel)
            .where(
                RoutingConfirmationModel.root_run_id == run.id,
                RoutingConfirmationModel.status == "pending",
            )
            .order_by(RoutingConfirmationModel.created_at.desc(), RoutingConfirmationModel.id.desc())
            .limit(1)
        )

    return ChatResponse(
        run_id=run.id,
        session_id=run.session_id,
        status=run.status,
        response=run.final_response,
        approval_id=approval_id,
        routing_confirmation_id=confirmation.id if confirmation else None,
        proposed_provider=confirmation.proposed_provider if confirmation else None,
        proposed_model=confirmation.proposed_model if confirmation else None,
        user_message_id=message_ids.get("user"),
        assistant_message_id=message_ids.get("assistant"),
        # Tool results remain available from persisted run details; replays do
        # not reconstruct or execute tool calls.
        tool_results=[],
    )


async def _close_pending_decisions_for_cancelled_run(db: AsyncSession, run_id: str) -> None:
    """Prevent an approval/confirmation racing with cancellation from resuming a terminal run."""
    child_run_ids = select(RunModel.id).where(
        or_(RunModel.id == run_id, RunModel.parent_run_id == run_id)
    )
    decided_at = utc_now()
    await db.execute(
        update(ApprovalModel)
        .where(ApprovalModel.run_id.in_(child_run_ids), ApprovalModel.status == "pending")
        .values(status="rejected", decision_notes="Run cancelled before approval.", decided_at=decided_at)
    )
    await db.execute(
        update(RoutingConfirmationModel)
        .where(
            or_(
                RoutingConfirmationModel.root_run_id == run_id,
                RoutingConfirmationModel.execution_run_id.in_(child_run_ids),
            ),
            RoutingConfirmationModel.status == "pending",
        )
        .values(status="rejected", decision_notes="Run cancelled before routing confirmation.", decided_at=decided_at)
    )


async def _replace_cancelled_run_response(db: AsyncSession, session_id: str, run_id: str, response: str) -> None:
    """Keep a late cancellation response consistent with any already-persisted assistant turn."""
    await db.execute(
        update(MessageModel)
        .where(
            MessageModel.session_id == session_id,
            MessageModel.role == "assistant",
            MessageModel.metadata_json["run_id"].as_string() == run_id,
        )
        .values(content=response)
    )


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
    request_fingerprint = _chat_request_fingerprint(req) if req.client_turn_id else None
    if req.client_turn_id:
        existing = await db.scalar(
            select(RunModel).where(
                RunModel.session_id == req.session_id,
                RunModel.client_turn_id == req.client_turn_id,
            )
        )
        if existing is not None:
            return await _existing_chat_response(
                db,
                existing,
                request_fingerprint=request_fingerprint or "",
            )

    run_id = str(uuid.uuid4())

    context_object_ids = list(dict.fromkeys(req.context_object_ids))
    if context_object_ids and not req.project_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="context_object_ids require a project_name scope.",
        )

    # 1. Ensure session exists
    session = await mem_service.get_or_create_session(req.session_id)
    if session.title in {"New Session", f"Session {session.id[:8]}"}:
        title = " ".join(req.message.split())
        if title:
            session.title = title[:255]
    session.updated_at = utc_now()
    if req.project_name:
        try:
            await mem_service.attach_session_to_project(req.session_id, req.project_name)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    from app.models.routing_resolver import resolve_routing_profile, apply_routing_profile_to_context
    from app.models.base import RoutingContext

    profile, scope = await resolve_routing_profile(db, session_id=req.session_id, project_name=req.project_name)
    
    # Base routing context for Root
    root_context = RoutingContext(
        session_id=req.session_id,
        run_id=run_id,
        task_type=req.task_type,
    )
    root_context = apply_routing_profile_to_context(
        profile,
        role="root",
        context=root_context,
        winning_scope=scope,
        message_override=req.model_override,
        reasoning_override=req.reasoning_override,
    )
    attachment_titles: dict[str, str] = {}
    if req.context_attachments:
        if not req.project_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="File content attachments require a project workspace scope.",
            )
        attachment_ids = [attachment.object_id for attachment in req.context_attachments]
        linked_ids = select(WorkspaceObjectProjectLinkModel.object_id).where(
            WorkspaceObjectProjectLinkModel.project_name == req.project_name
        )
        visible_attachment = or_(
            WorkspaceObjectModel.project_name == req.project_name,
            and_(
                WorkspaceObjectModel.project_name.is_(None),
                WorkspaceObjectModel.id.in_(linked_ids),
            ),
        )
        result = await db.execute(
            select(WorkspaceObjectModel).where(
                WorkspaceObjectModel.id.in_(attachment_ids),
                WorkspaceObjectModel.object_type == "file_reference",
                WorkspaceObjectModel.created_by == "user",
                visible_attachment,
            )
        )
        visible_files = {item.id: item for item in result.scalars()}
        if set(visible_files) != set(attachment_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A file content attachment is not a visible Library reference in this project.",
            )
        attachment_titles = {object_id: item.title for object_id, item in visible_files.items()}
        # File text is user data. A cloud route must pause at the durable
        # routing-confirmation boundary before any provider receives it.
        root_context.require_cloud_confirmation = True

    # 2. Persist Run entity in database
    run_record = RunModel(
        id=run_id,
        session_id=req.session_id,
        client_turn_id=req.client_turn_id,
        request_fingerprint=request_fingerprint,
        status=RunStatus.RUNNING.value,
        user_message=req.message,
        routing_snapshot_json={
            "profile_id": profile.id,
            "profile_version": profile.version,
            "winning_scope": root_context.winning_scope,
            "role": "root",
            "is_lock_all": root_context.is_lock_all,
            "privacy_policy": root_context.privacy_requirement.value,
            "fallback_policy": root_context.fallback_policy.value,
            "require_cloud_confirmation": root_context.require_cloud_confirmation,
            "explicit_model_override": root_context.explicit_model_override,
            "reasoning_policy": root_context.reasoning_policy.value if root_context.reasoning_policy else None,
            "reasoning_effort": root_context.reasoning_effort.value if root_context.reasoning_effort else None,
            "reasoning_bounds": {
                "min": root_context.reasoning_effort_min.value if root_context.reasoning_effort_min else None,
                "max": root_context.reasoning_effort_max.value if root_context.reasoning_effort_max else None,
            } if root_context.reasoning_policy and root_context.reasoning_policy.value == "adaptive" else None,
        }
    )
    db.add(run_record)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        if not req.client_turn_id:
            raise
        existing = await db.scalar(
            select(RunModel).where(
                RunModel.session_id == req.session_id,
                RunModel.client_turn_id == req.client_turn_id,
            )
        )
        if existing is None:
            raise
        return await _existing_chat_response(
            db,
            existing,
            request_fingerprint=request_fingerprint or "",
        )

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
    merged_metadata["winning_scope"] = root_context.winning_scope
    merged_metadata["is_lock_all"] = root_context.is_lock_all
    merged_metadata["global_fallback_policy"] = profile.global_fallback_policy.value
    
    if req.model_override:
        merged_metadata["model_override"] = req.model_override
    if req.reasoning_override:
        merged_metadata["reasoning_override"] = req.reasoning_override

    initial_state = create_initial_agent_state(
        run_id=run_id,
        session_id=req.session_id,
        user_message=req.message,
        project_name=req.project_name,
        metadata=merged_metadata,
    )
    initial_state["context_object_ids"] = context_object_ids
    initial_state["context_attachments"] = [
        {
            "object_id": attachment.object_id,
            "title": attachment_titles[attachment.object_id],
            "text": attachment.text,
        }
        for attachment in req.context_attachments
    ]

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

        await db.refresh(run_record)
        if run_record.cancel_requested_at is not None:
            await _close_pending_decisions_for_cancelled_run(db, run_id)
            run_record.status = RunStatus.CANCELLED.value
            run_record.final_response = (
                "Run cancelled. An operation already in progress may have completed "
                "before AURA observed the request."
            )
            run_record.error_message = None
            await _replace_cancelled_run_response(db, req.session_id, run_id, run_record.final_response)
            await db.commit()
            return ChatResponse(
                run_id=run_id,
                session_id=req.session_id,
                status=RunStatus.CANCELLED.value,
                response=run_record.final_response,
                tool_results=result_state.get("tool_results", []),
            )

        # 6. Check if execution was suspended via interrupt()
        if "__interrupt__" in result_state and len(result_state["__interrupt__"]) > 0:
            interrupt_val = result_state["__interrupt__"][0].value
            if isinstance(interrupt_val, dict) and interrupt_val.get("kind") == "routing_confirmation":
                confirmation_id = interrupt_val.get("confirmation_id")
                run_record.status = RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value
                run_record.final_response = "Cloud routing requires your confirmation."
                execution_run_id = interrupt_val.get("execution_run_id")
                if isinstance(execution_run_id, str) and execution_run_id != run_id:
                    execution_run = await db.get(RunModel, execution_run_id)
                    if execution_run is not None:
                        execution_run.status = RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value
                await db.commit()
                return ChatResponse(
                    run_id=run_id,
                    session_id=req.session_id,
                    status=RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value,
                    response=run_record.final_response,
                    routing_confirmation_id=confirmation_id,
                    proposed_provider=interrupt_val.get("proposed_provider"),
                    proposed_model=interrupt_val.get("proposed_model"),
                    tool_results=[],
                )

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
            user_message_id=result_state.get("persisted_user_message_id"),
            assistant_message_id=result_state.get("persisted_assistant_message_id"),
            tool_results=result_state.get("tool_results", []),
        )

    except Exception as e:
        logger.error(f"Error executing run '{run_id}': {e}", exc_info=True)
        await db.refresh(run_record)
        if run_record.cancel_requested_at is not None:
            await _close_pending_decisions_for_cancelled_run(db, run_id)
            run_record.status = RunStatus.CANCELLED.value
            run_record.final_response = (
                "Run cancelled. An operation already in progress may have completed "
                "before AURA observed the request."
            )
            run_record.error_message = None
            await _replace_cancelled_run_response(db, req.session_id, run_id, run_record.final_response)
            await db.commit()
            return ChatResponse(
                run_id=run_id,
                session_id=req.session_id,
                status=RunStatus.CANCELLED.value,
                response=run_record.final_response,
            )
        run_record.status = RunStatus.FAILED.value
        run_record.error_message = str(e)
        await db.commit()
        await trace_service.record_event(
            run_id=run_id,
            session_id=req.session_id,
            event_type="run_failed",
            payload={"error": str(e), "error_category": "graph_failure"},
        )
        if isinstance(e, AuraError):
            if isinstance(e, RoutingConfirmationRequired):
                code, http_status = "RoutingConfirmationRequired", status.HTTP_409_CONFLICT
            elif isinstance(e, ContextSelectionError):
                code, http_status = "ContextSelectionError", status.HTTP_422_UNPROCESSABLE_CONTENT
            elif isinstance(e, PrivacyBoundaryViolation):
                code, http_status = "PrivacyBoundaryViolation", status.HTTP_403_FORBIDDEN
            elif isinstance(e, ModelUnavailable):
                code, http_status = "ModelUnavailable", status.HTTP_422_UNPROCESSABLE_ENTITY
            elif isinstance(e, ModelCapabilityMismatch):
                code, http_status = "ModelCapabilityMismatch", status.HTTP_422_UNPROCESSABLE_ENTITY
            elif isinstance(e, ReasoningControlUnsupported):
                code, http_status = "ReasoningControlUnsupported", status.HTTP_422_UNPROCESSABLE_ENTITY
            elif isinstance(e, NoEligibleRoute):
                code, http_status = "NoEligibleRoute", status.HTTP_422_UNPROCESSABLE_ENTITY
            else:
                code, http_status = e.__class__.__name__, status.HTTP_400_BAD_REQUEST
            return JSONResponse(status_code=http_status, content={"error": code, "code": code, "message": e.message, "details": e.details})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {str(e)}",
        )
