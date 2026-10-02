"""Study session lifecycle backed by the shared workspace object graph."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import StudyCardResponse, StudyCardWrite, StudyReflectionWrite, StudySessionResponse, StudySessionWrite
from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel, WorkspaceObjectProjectLinkModel
from app.db.session import get_db
from app.memory.context_compiler import WorkspaceContextCompiler, stricter_privacy_requirement

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


async def _lock_study_session_creation(db: AsyncSession) -> None:
    """Serialize Study starts so concurrent requests cannot create overlapping timers."""
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:namespace), hashtext(:resource))"),
            {"namespace": "aura", "resource": "study:active-session"},
        )


async def _ensure_no_active_study_session(db: AsyncSession) -> None:
    result = await db.execute(
        select(WorkspaceObjectModel).where(
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type == "study_session",
            WorkspaceObjectModel.created_by == "user",
        )
    )
    for item in result.scalars():
        metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
        # Older sessions without an explicit completed status are still active,
        # matching the response projection's in_progress default.
        if metadata.get("status") != "completed":
            raise HTTPException(
                status_code=409,
                detail="Another Study session is already active. Complete it before starting a new one.",
            )


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
    is_library_material = False
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
    await _lock_study_session_creation(db)
    await _ensure_no_active_study_session(db)
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


def _study_card_response(item: WorkspaceObjectModel) -> StudyCardResponse:
    metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
    return StudyCardResponse(
        id=item.id,
        session_id=metadata.get("study_session_id", ""),
        question=item.title,
        answer=item.content or "",
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _get_user_study_session(db: AsyncSession, session_id: str) -> WorkspaceObjectModel:
    item = await db.get(WorkspaceObjectModel, session_id)
    if (
        item is None
        or item.project_name is not None
        or item.object_type != "study_session"
        or item.created_by != "user"
    ):
        raise HTTPException(status_code=404, detail="Study session not found.")
    return item


@router.get("/cards", response_model=list[StudyCardResponse])
async def list_study_cards(db: AsyncSession = Depends(get_db)) -> list[StudyCardResponse]:
    result = await db.execute(
        select(WorkspaceObjectModel)
        .where(
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type == "study_card",
            WorkspaceObjectModel.created_by == "user",
        )
        .order_by(WorkspaceObjectModel.created_at, WorkspaceObjectModel.id)
    )
    cards = []
    for item in result.scalars():
        metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
        if isinstance(metadata.get("study_session_id"), str):
            cards.append(_study_card_response(item))
    return cards


@router.post(
    "/sessions/{session_id}/cards",
    response_model=StudyCardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_study_card(
    session_id: str,
    body: StudyCardWrite,
    db: AsyncSession = Depends(get_db),
) -> StudyCardResponse:
    session = await _get_user_study_session(db, session_id)
    if not body.question.strip() or not body.answer.strip():
        raise HTTPException(status_code=422, detail="Study card question and answer must not be blank.")
    session_metadata = session.metadata_json if isinstance(session.metadata_json, dict) else {}
    privacy_requirement = (
        session_metadata.get("privacy_policy")
        if isinstance(session_metadata.get("privacy_policy"), str)
        else None
    )
    project_links = await db.execute(
        select(WorkspaceObjectProjectLinkModel.project_name)
        .where(WorkspaceObjectProjectLinkModel.object_id == session.id)
        .order_by(WorkspaceObjectProjectLinkModel.project_name)
    )
    project_names = list(project_links.scalars())
    for project_name in project_names:
        source_context = await WorkspaceContextCompiler(db).compile(project_name, [session.id])
        privacy_requirement = stricter_privacy_requirement(
            privacy_requirement,
            source_context.privacy_requirement,
        )
    card_metadata: dict[str, Any] = {"study_session_id": session.id}
    if privacy_requirement:
        card_metadata["privacy_policy"] = privacy_requirement
    card = WorkspaceObjectModel(
        project_name=None,
        object_type="study_card",
        created_by="user",
        title=body.question,
        content=body.answer,
        metadata_json=card_metadata,
    )
    db.add(card)
    await db.flush()

    for project_name in project_names:
        db.add(WorkspaceObjectProjectLinkModel(object_id=card.id, project_name=project_name))
        db.add(WorkspaceEdgeModel(
            project_name=project_name,
            source_object_id=session.id,
            target_object_id=card.id,
            relation_type="contains_card",
            edge_family="provenance",
            created_by="user",
        ))
    await db.commit()
    await db.refresh(card)
    return _study_card_response(card)


@router.put("/sessions/{session_id}/cards/{card_id}", response_model=StudyCardResponse)
async def update_study_card(
    session_id: str,
    card_id: str,
    body: StudyCardWrite,
    db: AsyncSession = Depends(get_db),
) -> StudyCardResponse:
    await _get_user_study_session(db, session_id)
    card = await db.get(WorkspaceObjectModel, card_id)
    metadata = card.metadata_json if card and isinstance(card.metadata_json, dict) else {}
    if (
        card is None
        or card.project_name is not None
        or card.object_type != "study_card"
        or card.created_by != "user"
        or metadata.get("study_session_id") != session_id
    ):
        raise HTTPException(status_code=404, detail="Study card not found.")
    if not body.question.strip() or not body.answer.strip():
        raise HTTPException(status_code=422, detail="Study card question and answer must not be blank.")
    card.title = body.question
    card.content = body.answer
    card.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(card)
    return _study_card_response(card)


@router.delete("/sessions/{session_id}/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_study_card(
    session_id: str,
    card_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_user_study_session(db, session_id)
    card = await db.get(WorkspaceObjectModel, card_id)
    metadata = card.metadata_json if card and isinstance(card.metadata_json, dict) else {}
    if (
        card is None
        or card.project_name is not None
        or card.object_type != "study_card"
        or card.created_by != "user"
        or metadata.get("study_session_id") != session_id
    ):
        raise HTTPException(status_code=404, detail="Study card not found.")
    await db.execute(
        sa_delete(WorkspaceEdgeModel).where(
            (WorkspaceEdgeModel.source_object_id == card_id)
            | (WorkspaceEdgeModel.target_object_id == card_id)
        )
    )
    await db.execute(
        sa_delete(WorkspaceObjectProjectLinkModel).where(
            WorkspaceObjectProjectLinkModel.object_id == card_id
        )
    )
    await db.delete(card)
    await db.commit()


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
