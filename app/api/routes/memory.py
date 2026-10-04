"""Project and session memory inspection and lifecycle endpoints."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import decode_timestamp_id_cursor, set_next_cursor_header
from app.api.schemas import MemoryActivationUpdate, MemoryItemResponse
from app.db.models import MemoryModel
from app.db.session import get_db

router = APIRouter(prefix="/v1/memory", tags=["Memory"])


@router.get("", response_model=List[MemoryItemResponse])
async def list_memories(
    response: Response,
    project_name: Optional[str] = Query(None, description="Optional project name scope"),
    session_id: Optional[str] = Query(None, description="Optional session ID scope"),
    memory_type: Optional[str] = Query(default=None, max_length=32),
    cursor: Optional[str] = Query(default=None, max_length=512),
    page_size: int = Query(default=25, ge=1, le=100),
    include_inactive: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> List[MemoryItemResponse]:
    """Read-only listing of persisted project and semantic memories with provenance."""
    stmt = select(MemoryModel)
    if project_name:
        stmt = stmt.where(MemoryModel.project_name == project_name)
    if session_id:
        stmt = stmt.where(MemoryModel.session_id == session_id)
    if memory_type:
        stmt = stmt.where(MemoryModel.memory_type == memory_type)
        if memory_type == "profile":
            stmt = stmt.where(MemoryModel.project_name.is_(None))
    if not include_inactive:
        stmt = stmt.where(MemoryModel.is_active.is_(True))
    if cursor is not None:
        cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
        stmt = stmt.where(or_(
            MemoryModel.created_at < cursor_created_at,
            and_(MemoryModel.created_at == cursor_created_at, MemoryModel.id < cursor_id),
        ))

    stmt = stmt.order_by(MemoryModel.created_at.desc(), MemoryModel.id.desc()).limit(page_size + 1)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    records = set_next_cursor_header(
        response,
        rows,
        page_size,
        timestamp_for=lambda item: item.created_at,
        id_for=lambda item: item.id,
    )

    return [
        MemoryItemResponse(
            id=m.id,
            session_id=m.session_id,
            memory_type=m.memory_type,
            project_name=m.project_name,
            key=m.key,
            content=m.content,
            confidence=m.confidence,
            is_active=m.is_active,
            supersedes_id=m.supersedes_id,
            superseded_by_id=m.superseded_by_id,
            metadata_json=m.metadata_json,
            created_at=m.created_at,
        )
        for m in records
    ]


def _memory_response(memory: MemoryModel) -> MemoryItemResponse:
    return MemoryItemResponse(
        id=memory.id,
        session_id=memory.session_id,
        memory_type=memory.memory_type,
        project_name=memory.project_name,
        key=memory.key,
        content=memory.content,
        confidence=memory.confidence,
        is_active=memory.is_active,
        supersedes_id=memory.supersedes_id,
        superseded_by_id=memory.superseded_by_id,
        metadata_json=memory.metadata_json,
        created_at=memory.created_at,
    )


@router.get("/by-id/{memory_id}", response_model=MemoryItemResponse)
async def get_scoped_memory(
    memory_id: str,
    project_name: Optional[str] = Query(default=None, min_length=1, max_length=255),
    session_id: Optional[str] = Query(default=None, min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> MemoryItemResponse:
    """Read one memory by ID, scoped to the visible project or source session."""
    scope_filters = []
    if project_name:
        scope_filters.append(MemoryModel.project_name == project_name.strip())
    if session_id:
        scope_filters.append(MemoryModel.session_id == session_id.strip())
    if not scope_filters:
        raise HTTPException(status_code=422, detail="A project or session scope is required.")

    result = await db.execute(select(MemoryModel).where(
        MemoryModel.id == memory_id,
        or_(*scope_filters),
    ))
    memory = result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found in this workspace scope.")
    return _memory_response(memory)


@router.get("/profile/{memory_id}", response_model=MemoryItemResponse)
async def get_profile_memory(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
) -> MemoryItemResponse:
    """Read one cross-project profile memory by ID."""
    result = await db.execute(select(MemoryModel).where(
        MemoryModel.id == memory_id,
        MemoryModel.memory_type == "profile",
        MemoryModel.project_name.is_(None),
    ))
    memory = result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=404, detail="Profile memory not found.")
    return _memory_response(memory)


@router.patch("/projects/{project_name}/{memory_id}", response_model=MemoryItemResponse)
async def set_project_memory_active(
    project_name: str,
    memory_id: str,
    body: MemoryActivationUpdate,
    db: AsyncSession = Depends(get_db),
) -> MemoryItemResponse:
    """Deactivate or restore one project memory without deleting its provenance."""
    normalized_project = project_name.strip()
    if not normalized_project:
        raise HTTPException(status_code=422, detail="Project name must not be blank.")

    return await _set_memory_active(
        db,
        memory_id=memory_id,
        memory_type="project",
        project_name=normalized_project,
        not_found_detail="Project memory not found.",
        is_active=body.is_active,
    )


@router.patch("/profile/{memory_id}", response_model=MemoryItemResponse)
async def set_profile_memory_active(
    memory_id: str,
    body: MemoryActivationUpdate,
    db: AsyncSession = Depends(get_db),
) -> MemoryItemResponse:
    """Deactivate or restore one cross-project profile memory."""
    return await _set_memory_active(
        db,
        memory_id=memory_id,
        memory_type="profile",
        project_name=None,
        not_found_detail="Profile memory not found.",
        is_active=body.is_active,
    )


async def _set_memory_active(
    db: AsyncSession,
    *,
    memory_id: str,
    memory_type: str,
    project_name: Optional[str],
    not_found_detail: str,
    is_active: bool,
) -> MemoryItemResponse:
    scope_filter = (
        MemoryModel.project_name == project_name
        if project_name is not None
        else MemoryModel.project_name.is_(None)
    )
    result = await db.execute(select(MemoryModel).where(
        MemoryModel.id == memory_id,
        MemoryModel.memory_type == memory_type,
        scope_filter,
    ))
    memory = result.scalar_one_or_none()
    if memory is None:
        raise HTTPException(status_code=404, detail=not_found_detail)

    if is_active and not memory.is_active:
        active_query = select(MemoryModel.id).where(
            MemoryModel.memory_type == memory.memory_type,
            scope_filter,
            MemoryModel.key == memory.key,
            MemoryModel.is_active.is_(True),
            MemoryModel.id != memory.id,
        ).limit(1)
        active_result = await db.execute(active_query)
        if active_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="An active memory already uses this key. Deactivate it before restoring this version.",
            )

    memory.is_active = is_active
    await db.commit()
    await db.refresh(memory)
    return MemoryItemResponse(
        id=memory.id,
        session_id=memory.session_id,
        memory_type=memory.memory_type,
        project_name=memory.project_name,
        key=memory.key,
        content=memory.content,
        confidence=memory.confidence,
        is_active=memory.is_active,
        supersedes_id=memory.supersedes_id,
        superseded_by_id=memory.superseded_by_id,
        metadata_json=memory.metadata_json,
        created_at=memory.created_at,
    )
