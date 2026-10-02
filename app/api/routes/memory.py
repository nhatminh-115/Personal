"""Read-only project and session memory inspection endpoint: GET /v1/memory."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import decode_timestamp_id_cursor, set_next_cursor_header
from app.api.schemas import MemoryItemResponse
from app.db.models import MemoryModel
from app.db.session import get_db

router = APIRouter(prefix="/v1/memory", tags=["Memory"])


@router.get("", response_model=List[MemoryItemResponse])
async def list_memories(
    response: Response,
    project_name: Optional[str] = Query(None, description="Optional project name scope"),
    session_id: Optional[str] = Query(None, description="Optional session ID scope"),
    cursor: Optional[str] = Query(default=None, max_length=512),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> List[MemoryItemResponse]:
    """Read-only listing of persisted project and semantic memories with provenance."""
    stmt = select(MemoryModel)
    if project_name:
        stmt = stmt.where(MemoryModel.project_name == project_name)
    if session_id:
        stmt = stmt.where(MemoryModel.session_id == session_id)
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
            metadata_json=m.metadata_json,
            created_at=m.created_at,
        )
        for m in records
    ]
