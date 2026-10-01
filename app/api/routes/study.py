"""Study session lifecycle backed by the shared workspace object graph."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import StudySessionResponse, StudySessionWrite
from app.db.models import WorkspaceObjectModel
from app.db.session import get_db

router = APIRouter(prefix="/v1/study", tags=["Study"])


def _study_session_response(item: WorkspaceObjectModel) -> StudySessionResponse:
    metadata = item.metadata_json or {}
    completed_at = metadata.get("completed_at")
    status_value = "completed" if metadata.get("status") == "completed" else "in_progress"
    return StudySessionResponse(
        id=item.id,
        track_id=metadata.get("track_id", ""),
        track_title=item.title,
        material_id=metadata.get("material_id") if isinstance(metadata.get("material_id"), str) else None,
        status=status_value,
        started_at=item.created_at,
        completed_at=datetime.fromisoformat(completed_at) if isinstance(completed_at, str) else None,
    )


@router.get("/sessions", response_model=list[StudySessionResponse])
async def list_study_sessions(db: AsyncSession = Depends(get_db)) -> list[StudySessionResponse]:
    result = await db.execute(
        select(WorkspaceObjectModel)
        .where(
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type == "study_session",
            WorkspaceObjectModel.created_by == "user",
        )
        .order_by(WorkspaceObjectModel.created_at.desc(), WorkspaceObjectModel.id)
    )
    return [_study_session_response(item) for item in result.scalars()]


@router.post("/sessions", response_model=StudySessionResponse, status_code=status.HTTP_201_CREATED)
async def start_study_session(
    body: StudySessionWrite,
    db: AsyncSession = Depends(get_db),
) -> StudySessionResponse:
    track_id = body.track_id.strip()
    track_title = body.track_title.strip()
    if not track_id or not track_title:
        raise HTTPException(status_code=422, detail="Study track ID and title must not be blank.")
    material_id = body.material_id.strip() if body.material_id else None
    if material_id:
        material = await db.get(WorkspaceObjectModel, material_id)
        material_metadata = material.metadata_json if material and isinstance(material.metadata_json, dict) else {}
        if (
            material is None
            or material.project_name is not None
            or material.object_type != "file_reference"
            or material.created_by != "user"
            or material_metadata.get("collection") not in {"Study", "Research"}
        ):
            raise HTTPException(status_code=404, detail="Study material not found in the personal Library.")
        # The reference is the durable identity; use its current canonical title
        # and store the link on the Study object without copying file contents.
        track_id = material.id
        track_title = material.title
    item = WorkspaceObjectModel(
        project_name=None,
        object_type="study_session",
        created_by="user",
        title=track_title,
        content="",
        metadata_json={
            "track_id": track_id,
            "status": "in_progress",
            **({"material_id": material_id} if material_id else {}),
        },
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _study_session_response(item)


@router.post("/sessions/{session_id}/complete", response_model=StudySessionResponse)
async def complete_study_session(session_id: str, db: AsyncSession = Depends(get_db)) -> StudySessionResponse:
    item = await db.get(WorkspaceObjectModel, session_id)
    if (
        item is None
        or item.project_name is not None
        or item.object_type != "study_session"
        or item.created_by != "user"
    ):
        raise HTTPException(status_code=404, detail="Study session not found.")
    metadata: dict[str, Any] = dict(item.metadata_json or {})
    if metadata.get("status") != "completed":
        completed_at = datetime.now(timezone.utc)
        metadata.update(status="completed", completed_at=completed_at.isoformat())
        item.metadata_json = metadata
        item.updated_at = completed_at
        await db.commit()
        await db.refresh(item)
    return _study_session_response(item)
