"""Sessions inspection endpoint: GET /v1/sessions."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import decode_timestamp_id_cursor, encode_timestamp_id_cursor
from app.api.schemas import (
    ApprovalResponse,
    MessageResponse,
    SessionDetailResponse,
    SessionExecutionStateResponse,
    SessionSummaryResponse,
)
from app.db.models import ApprovalModel, MessageModel, RunEventModel, RunModel, SessionModel, WorkspaceObjectModel
from app.db.session import get_db

router = APIRouter(prefix="/v1/sessions", tags=["Sessions"])


@router.get("/{session_id}/state", response_model=SessionExecutionStateResponse)
async def get_session_execution_state(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> SessionExecutionStateResponse:
    """Return the latest root run and any still-pending approval for a session."""
    session = await db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

    result = await db.execute(
        select(RunModel)
        .where(RunModel.session_id == session_id, RunModel.parent_run_id.is_(None))
        .order_by(RunModel.updated_at.desc(), RunModel.created_at.desc(), RunModel.id.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if run is None:
        return SessionExecutionStateResponse(session_id=session_id)

    approval_response = None
    if run.status == "waiting_for_approval":
        run_ids_result = await db.execute(
            select(RunModel.id).where((RunModel.id == run.id) | (RunModel.parent_run_id == run.id))
        )
        run_ids = list(run_ids_result.scalars())
        approval_result = await db.execute(
            select(ApprovalModel)
            .where(ApprovalModel.status == "pending", ApprovalModel.run_id.in_(run_ids))
            .order_by(ApprovalModel.created_at.desc(), ApprovalModel.id.desc())
            .limit(1)
        )
        approval = approval_result.scalar_one_or_none()
        if approval is not None:
            approval_response = ApprovalResponse.model_validate(approval, from_attributes=True)

    return SessionExecutionStateResponse(
        session_id=session_id,
        run_id=run.id,
        run_status=run.status,
        approval=approval_response,
    )


@router.get("", response_model=List[SessionSummaryResponse])
async def list_sessions(
    response: Response,
    project_name: Optional[str] = Query(default=None, max_length=128),
    cursor: Optional[str] = Query(default=None, max_length=512),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> List[SessionSummaryResponse]:
    """List one bounded page of recent sessions, optionally scoped to a project."""
    stmt = select(SessionModel)
    if project_name:
        stmt = stmt.where(SessionModel.project_name == project_name)
    if cursor:
        cursor_updated_at, cursor_id = decode_timestamp_id_cursor(cursor)
        stmt = stmt.where(
            or_(
                SessionModel.updated_at < cursor_updated_at,
                and_(SessionModel.updated_at == cursor_updated_at, SessionModel.id < cursor_id),
            )
        )
    stmt = stmt.order_by(SessionModel.updated_at.desc(), SessionModel.id.desc()).limit(page_size + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    has_next_page = len(rows) > page_size
    sessions = rows[:page_size]
    if has_next_page and sessions:
        last = sessions[-1]
        response.headers["X-Next-Cursor"] = encode_timestamp_id_cursor(last.updated_at, last.id)
    return [
        SessionSummaryResponse(
            id=s.id,
            title=s.title,
            project_name=s.project_name,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_details(
    session_id: str,
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> SessionDetailResponse:
    """Inspect conversation history and state of a session."""
    session = await db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    message_query = select(MessageModel).where(MessageModel.session_id == session_id)
    if cursor:
        cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
        message_query = message_query.where(
            or_(
                MessageModel.created_at < cursor_created_at,
                and_(MessageModel.created_at == cursor_created_at, MessageModel.id < cursor_id),
            )
        )
    message_query = message_query.order_by(MessageModel.created_at.desc(), MessageModel.id.desc()).limit(limit + 1)
    message_result = await db.execute(message_query)
    descending_messages = list(message_result.scalars().all())
    has_older_messages = len(descending_messages) > limit
    page_descending = descending_messages[:limit]
    messages = list(reversed(page_descending))
    messages_next_cursor = (
        encode_timestamp_id_cursor(page_descending[-1].created_at, page_descending[-1].id)
        if has_older_messages and page_descending else None
    )
    message_ids = [message.id for message in messages]
    run_id_by_message: dict[str, str] = {}
    if message_ids:
        object_result = await db.execute(
            select(WorkspaceObjectModel.source_message_id, WorkspaceObjectModel.metadata_json)
            .where(WorkspaceObjectModel.source_message_id.in_(message_ids))
        )
        for message_id, metadata in object_result.all():
            run_id = (metadata or {}).get("run_id") if isinstance(metadata, dict) else None
            if isinstance(message_id, str) and isinstance(run_id, str):
                run_id_by_message[message_id] = run_id
    run_ids = set(run_id_by_message.values())
    manifest_by_run: dict[str, dict] = {}
    routing_by_run: dict[str, dict] = {}
    if run_ids:
        result = await db.execute(
            select(RunEventModel)
            .where(
                RunEventModel.run_id.in_(run_ids),
                RunEventModel.event_type.in_({
                    "context_compiled",
                    "model_selected",
                    "reasoning_effort_selected",
                }),
            )
            .order_by(RunEventModel.created_at, RunEventModel.id)
        )
        for event in result.scalars():
            payload = event.payload if isinstance(event.payload, dict) else {}
            if event.event_type == "model_selected":
                routing = routing_by_run.setdefault(event.run_id, {})
                for key in ("provider", "model", "agent_role"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        routing[{"agent_role": "role"}.get(key, key)] = value
            elif event.event_type == "reasoning_effort_selected":
                effort = payload.get("selected_effort")
                if isinstance(effort, str):
                    routing_by_run.setdefault(event.run_id, {})["reasoning_effort"] = effort
            if event.event_type != "context_compiled":
                continue
            raw_objects = payload.get("objects")
            objects = []
            if isinstance(raw_objects, list):
                for item in raw_objects:
                    if not isinstance(item, dict):
                        continue
                    object_id = item.get("object_id")
                    object_type = item.get("object_type")
                    if not isinstance(object_id, str) or not isinstance(object_type, str):
                        continue
                    compiled_item = {
                        "object_id": object_id,
                        "object_type": object_type,
                        "selected_by_user": item.get("selected_by_user") is True,
                    }
                    source_ids = item.get("source_object_ids")
                    if isinstance(source_ids, list):
                        compiled_item["source_object_ids"] = [value for value in source_ids if isinstance(value, str)]
                    selected_sections = item.get("selected_sections")
                    if isinstance(selected_sections, dict):
                        compiled_item["selected_sections"] = {
                            key: value for key, value in selected_sections.items()
                            if isinstance(key, str) and (isinstance(value, bool) or value is None)
                        }
                    objects.append(compiled_item)
            estimated_tokens = payload.get("estimated_tokens")
            manifest_by_run[event.run_id] = {
                "objects": objects,
                **({"estimated_tokens": estimated_tokens} if isinstance(estimated_tokens, int) and not isinstance(estimated_tokens, bool) else {}),
            }

    return SessionDetailResponse(
        id=session.id,
        title=session.title,
        project_name=session.project_name,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages_next_cursor=messages_next_cursor,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                run_id=run_id_by_message.get(m.id),
                context_manifest=manifest_by_run.get(run_id_by_message.get(m.id, "")),
                routing_provenance=routing_by_run.get(run_id_by_message.get(m.id, "")),
            )
            for m in messages
        ],
    )
