"""Study session lifecycle backed by the shared workspace object graph."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import StudyReflectionWrite, StudySessionResponse, StudySessionWrite
from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel, WorkspaceObjectProjectLinkModel
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
        material_project_name=(
            metadata.get("material_project_name")
            if isinstance(metadata.get("material_project_name"), str)
            else None
        ),
        status=status_value,
        reflection=item.content or "",
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
    material_project_name = body.material_project_name.strip() if body.material_project_name else None
    is_verified_research_claim = False
    material_project_names: list[str] = []
    if material_id:
        material = await db.get(WorkspaceObjectModel, material_id)
        material_metadata = material.metadata_json if material and isinstance(material.metadata_json, dict) else {}
        is_library_material = (
            material is not None
            and material.project_name is None
            and material.object_type == "file_reference"
            and material.created_by == "user"
            and material_metadata.get("collection") in {"Study", "Research"}
        )
        if is_library_material:
            linked_projects = await db.execute(
                select(WorkspaceObjectProjectLinkModel.project_name)
                .where(WorkspaceObjectProjectLinkModel.object_id == material.id)
                .order_by(WorkspaceObjectProjectLinkModel.project_name)
            )
            material_project_names = list(linked_projects.scalars())

        is_verified_research_claim = (
            material is not None
            and material.project_name is not None
            and material.project_name == material_project_name
            and material.object_type == "research_claim"
            and material.created_by == "research"
            and material_metadata.get("verification_status") == "verified"
        )
        if not (is_library_material or is_verified_research_claim):
            raise HTTPException(status_code=404, detail="Study source not found or not eligible.")
        # The source object is the durable identity. Keep its canonical title and
        # project scope without copying research or file contents.
        track_id = material.id
        track_title = material.title
        material_project_name = material.project_name if is_verified_research_claim else None
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
            **({"material_project_name": material_project_name} if material_project_name else {}),
        },
    )
    db.add(item)
    await db.flush()
    if is_verified_research_claim and material_project_name and material_id:
        # Study is a user-owned workspace object. Link it into the source project graph
        # and retain the verified research claim as first-class provenance.
        db.add(WorkspaceObjectProjectLinkModel(
            object_id=item.id,
            project_name=material_project_name,
        ))
        db.add(WorkspaceEdgeModel(
            project_name=material_project_name,
            source_object_id=material_id,
            target_object_id=item.id,
            relation_type="studied_in",
            edge_family="provenance",
            created_by="user",
        ))
    elif is_library_material and material_id:
        # A Study session follows the Library reference into the same project graphs
        # without copying the referenced file contents into the session.
        for project_name in material_project_names:
            db.add(WorkspaceObjectProjectLinkModel(
                object_id=item.id,
                project_name=project_name,
            ))
            db.add(WorkspaceEdgeModel(
                project_name=project_name,
                source_object_id=material_id,
                target_object_id=item.id,
                relation_type="studied_from",
                edge_family="provenance",
                created_by="user",
            ))
    await db.commit()
    await db.refresh(item)
    return _study_session_response(item)


@router.put("/sessions/{session_id}/reflection", response_model=StudySessionResponse)
async def update_study_reflection(
    session_id: str,
    body: StudyReflectionWrite,
    db: AsyncSession = Depends(get_db),
) -> StudySessionResponse:
    item = await db.get(WorkspaceObjectModel, session_id)
    if (
        item is None
        or item.project_name is not None
        or item.object_type != "study_session"
        or item.created_by != "user"
    ):
        raise HTTPException(status_code=404, detail="Study session not found.")
    item.content = body.reflection
    item.updated_at = datetime.now(timezone.utc)
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
