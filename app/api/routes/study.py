"""Durable focused sessions for AURA Study."""

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import StudySessionResponse, StudySessionStart
from app.db.models import StudySessionModel, utc_now
from app.db.session import get_db

router = APIRouter(prefix="/v1/study", tags=["Study"])


def _response(session: StudySessionModel) -> StudySessionResponse:
    return StudySessionResponse(
        id=session.id,
        track_id=session.track_id,
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        duration_seconds=session.duration_seconds,
    )


@router.get("/sessions", response_model=list[StudySessionResponse])
async def list_study_sessions(db: AsyncSession = Depends(get_db)) -> list[StudySessionResponse]:
    result = await db.execute(
        select(StudySessionModel)
        .order_by(StudySessionModel.started_at.desc(), StudySessionModel.id)
        .limit(200)
    )
    return [_response(session) for session in result.scalars()]


@router.post("/sessions", response_model=StudySessionResponse, status_code=status.HTTP_201_CREATED)
async def start_study_session(
    body: StudySessionStart,
    db: AsyncSession = Depends(get_db),
) -> StudySessionResponse:
    if body.id:
        existing = await db.get(StudySessionModel, body.id)
        if existing is not None:
            if existing.track_id != body.track_id:
                raise HTTPException(status_code=409, detail="Study session ID is already used by another track.")
            return _response(existing)

    active_result = await db.execute(
        select(StudySessionModel.id).where(StudySessionModel.status == "active").limit(1)
    )
    if active_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Finish the active Study session before starting another.")

    session = StudySessionModel(id=body.id, track_id=body.track_id, status="active", started_at=utc_now())
    db.add(session)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Another Study session became active. Finish it before retrying.") from exc
    await db.refresh(session)
    return _response(session)


@router.post("/sessions/{session_id}/complete", response_model=StudySessionResponse)
async def complete_study_session(session_id: str, db: AsyncSession = Depends(get_db)) -> StudySessionResponse:
    session = await db.get(StudySessionModel, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Study session not found.")
    if session.status == "completed":
        return _response(session)

    completed_at = utc_now()
    started_at = session.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    session.status = "completed"
    session.completed_at = completed_at
    session.duration_seconds = max(0, int((completed_at - started_at).total_seconds()))
    await db.commit()
    await db.refresh(session)
    return _response(session)
