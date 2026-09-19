"""Read-only project and session memory inspection endpoint: GET /v1/memory."""

from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import MemoryItemResponse
from app.db.models import MemoryModel
from app.db.session import get_db

router = APIRouter(prefix="/v1/memory", tags=["Memory"])


@router.get("", response_model=List[MemoryItemResponse])
async def list_memories(
    project_name: Optional[str] = Query(None, description="Optional project name scope"),
    session_id: Optional[str] = Query(None, description="Optional session ID scope"),
    db: AsyncSession = Depends(get_db),
) -> List[MemoryItemResponse]:
    """Read-only listing of persisted project and semantic memories with provenance."""
    stmt = select(MemoryModel)
    if project_name:
        stmt = stmt.where(MemoryModel.project_name == project_name)
    if session_id:
        stmt = stmt.where(MemoryModel.session_id == session_id)

    stmt = stmt.order_by(MemoryModel.created_at.desc()).limit(100)
    result = await db.execute(stmt)
    records = list(result.scalars().all())

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
