"""Sessions inspection endpoint: GET /v1/sessions."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_memory_service
from app.api.schemas import MessageResponse, SessionDetailResponse, SessionSummaryResponse
from app.db.models import RunEventModel, SessionModel, WorkspaceObjectModel
from app.db.session import get_db
from app.memory.base import MemoryService

router = APIRouter(prefix="/v1/sessions", tags=["Sessions"])


@router.get("", response_model=List[SessionSummaryResponse])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
) -> List[SessionSummaryResponse]:
    """List recent conversation sessions ordered by last update."""
    stmt = select(SessionModel).order_by(SessionModel.updated_at.desc()).limit(50)
    result = await db.execute(stmt)
    sessions = list(result.scalars().all())
    return [
        SessionSummaryResponse(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session_details(
    session_id: str,
    mem_service: MemoryService = Depends(get_memory_service),
    db: AsyncSession = Depends(get_db),
) -> SessionDetailResponse:
    """Inspect conversation history and state of a session."""
    session = await db.get(SessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    messages = await mem_service.get_session_messages(session_id, limit=100)
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
        created_at=session.created_at,
        updated_at=session.updated_at,
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
