"""Sessions inspection endpoint: GET /v1/sessions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from typing import List
from sqlalchemy import select
from app.api.dependencies import get_memory_service
from app.api.schemas import MessageResponse, SessionDetailResponse, SessionSummaryResponse
from app.db.models import SessionModel
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
) -> SessionDetailResponse:
    """Inspect conversation history and state of a session."""
    session = await mem_service.get_or_create_session(session_id)
    messages = await mem_service.get_session_messages(session_id, limit=100)

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
            )
            for m in messages
        ],
    )
