"""Project-scoped durable workspace objects and graph relationships."""

import base64
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import String, and_, bindparam, case, delete as sa_delete, func, or_, select, text, update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    WorkspaceContextPreviewRequest,
    WorkspaceContextPreviewResponse,
    WorkspaceEdgeBatchDelete,
    WorkspaceEdgeBatchRestore,
    WorkspaceEdgeCreate,
    WorkspaceEdgeResponse,
    WorkspaceExecutionEventResponse,
    WorkspaceExecutionHistoryResponse,
    WorkspaceExecutionTraceResponse,
    WorkspaceGraphResponse,
    WorkspaceLayoutResponse,
    WorkspaceLayoutWrite,
    WorkspaceLibraryReferenceResponse,
    WorkspaceLibraryReferenceWrite,
    WorkspaceProjectResponse,
    WorkspaceProjectArchiveWrite,
    WorkspaceProjectWrite,
    WorkspaceSummaryResponse,
    WorkspaceSearchResult,
    WorkspaceNoteResponse,
    WorkspaceNoteWrite,
    WorkspaceObjectCreate,
    WorkspaceObjectResponse,
    WorkspaceObjectUpdate,
    WorkspaceSessionResponse,
)
from app.api.pagination import (
    MAX_COLLECTION_PAGE_SIZE,
    decode_timestamp_id_cursor,
    encode_timestamp_id_cursor,
    set_next_cursor_header,
)
from app.api.dependencies import get_memory_service, get_tool_registry
from app.db.models import (
    RunEventModel,
    RunModel,
    SessionModel,
    WorkspaceEdgeModel,
    WorkspaceLayoutModel,
    WorkspaceObjectModel,
    WorkspaceObjectProjectLinkModel,
    WorkspaceProjectModel,
)
from app.db.session import get_db
from app.memory.base import MemoryService
from app.observability.payloads import safe_operational_error_metadata
from app.memory.context_compiler import WorkspaceContextCompiler, split_context_capabilities
from app.capabilities.registry import UnresolvedCapabilitiesError
from app.tools.registry import ToolRegistry

router = APIRouter(prefix="/v1/workspace", tags=["Workspace"])
MAX_WORKSPACE_COLLECTION_PAGE_SIZE = MAX_COLLECTION_PAGE_SIZE


@router.get("/summary", response_model=WorkspaceSummaryResponse)
async def get_workspace_summary(
    project_name: str | None = Query(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceSummaryResponse:
    note_filter = (
        WorkspaceObjectModel.project_name.is_(None),
        WorkspaceObjectModel.object_type == "manual_note",
        WorkspaceObjectModel.created_by == "user",
    )
    library_filter = (
        WorkspaceObjectModel.project_name.is_(None),
        WorkspaceObjectModel.object_type == "file_reference",
        WorkspaceObjectModel.created_by == "user",
    )

    async def count(query) -> int:
        return int(await db.scalar(query) or 0)

    note_count = await count(select(func.count()).select_from(WorkspaceObjectModel).where(*note_filter))
    library_count = await count(select(func.count()).select_from(WorkspaceObjectModel).where(*library_filter))
    linked_library_count = await count(
        select(func.count(func.distinct(WorkspaceObjectModel.id)))
        .select_from(WorkspaceObjectModel)
        .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
        .where(*library_filter)
    )
    project_note_count = 0
    project_library_count = 0
    if project_name:
        project_link = WorkspaceObjectProjectLinkModel.project_name == project_name
        project_note_count = await count(
            select(func.count(func.distinct(WorkspaceObjectModel.id)))
            .select_from(WorkspaceObjectModel)
            .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
            .where(*note_filter, project_link)
        )
        project_library_count = await count(
            select(func.count(func.distinct(WorkspaceObjectModel.id)))
            .select_from(WorkspaceObjectModel)
            .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
            .where(*library_filter, project_link)
        )
    return WorkspaceSummaryResponse(
        note_count=note_count,
        library_count=library_count,
        linked_library_count=linked_library_count,
        project_name=project_name,
        project_note_count=project_note_count,
        project_library_count=project_library_count,
    )


def _descending_timestamp_cursor_filter(timestamp_column, id_column, cursor: str):
    cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
    return or_(
        timestamp_column < cursor_created_at,
        and_(timestamp_column == cursor_created_at, id_column > cursor_id),
    )


def _set_next_cursor(response: Response, rows: list, page_size: int, timestamp_field: str = "created_at") -> list:
    return set_next_cursor_header(
        response, rows, page_size,
        timestamp_for=lambda item: getattr(item, timestamp_field),
        id_for=lambda item: item.id,
    )


def _decode_workspace_search_cursor(cursor: str) -> tuple[int, datetime, str]:
    try:
        encoded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
        if not isinstance(payload, list) or len(payload) != 3:
            raise ValueError("invalid cursor payload")
        rank, timestamp_text, object_id = payload
        if isinstance(rank, bool) or not isinstance(rank, int) or rank not in {0, 1, 2, 3}:
            raise ValueError("invalid search rank")
        if not isinstance(timestamp_text, str) or not isinstance(object_id, str) or not object_id or len(object_id) > 36:
            raise ValueError("invalid cursor values")
        timestamp = datetime.fromisoformat(timestamp_text)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return rank, timestamp, object_id
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid workspace search cursor.") from exc


def _encode_workspace_search_cursor(rank: int, item: WorkspaceObjectModel) -> str:
    payload = json.dumps([rank, item.updated_at.isoformat(), item.id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


@router.get("/projects", response_model=list[WorkspaceProjectResponse])
async def list_workspace_projects(
    response: Response,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int = Query(default=100, ge=1, le=MAX_WORKSPACE_COLLECTION_PAGE_SIZE),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceProjectResponse]:
    query = select(WorkspaceProjectModel)
    if not include_archived:
        query = query.where(WorkspaceProjectModel.archived_at.is_(None))
    if cursor is not None:
        cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
        query = query.where(or_(
            WorkspaceProjectModel.created_at > cursor_created_at,
            and_(WorkspaceProjectModel.created_at == cursor_created_at, WorkspaceProjectModel.id > cursor_id),
        ))
    result = await db.execute(
        query.order_by(WorkspaceProjectModel.created_at, WorkspaceProjectModel.id).limit(page_size + 1)
    )
    items = _set_next_cursor(response, list(result.scalars()), page_size)
    return [WorkspaceProjectResponse.model_validate(item, from_attributes=True) for item in items]


async def _set_workspace_project_archived(
    project_id: str,
    archived: bool,
    expected_revision: int,
    db: AsyncSession,
) -> WorkspaceProjectResponse:
    project = await db.get(WorkspaceProjectModel, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace project not found.")
    if project.revision != expected_revision:
        raise HTTPException(status_code=409, detail={
            "code": "WorkspaceProjectRevisionConflict",
            "message": "Workspace project archive state changed since it was loaded.",
            "current_revision": project.revision,
        })
    if archived and project.archived_at is None:
        archived_at = datetime.now(timezone.utc)
    elif not archived and project.archived_at is not None:
        archived_at = None
    else:
        return WorkspaceProjectResponse.model_validate(project, from_attributes=True)
    updated = await db.execute(
        sa_update(WorkspaceProjectModel)
        .where(WorkspaceProjectModel.id == project_id, WorkspaceProjectModel.revision == expected_revision)
        .values(archived_at=archived_at, revision=WorkspaceProjectModel.revision + 1)
        .returning(WorkspaceProjectModel.revision)
    )
    revision = updated.scalar_one_or_none()
    if revision is None:
        await db.rollback()
        current_revision = await db.scalar(select(WorkspaceProjectModel.revision).where(WorkspaceProjectModel.id == project_id))
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Workspace project not found.")
        raise HTTPException(status_code=409, detail={
            "code": "WorkspaceProjectRevisionConflict",
            "message": "Workspace project archive state changed since it was loaded.",
            "current_revision": current_revision,
        })
    await db.commit()
    await db.refresh(project)
    return WorkspaceProjectResponse.model_validate(project, from_attributes=True)


@router.post("/projects/{project_id}/archive", response_model=WorkspaceProjectResponse)
async def archive_workspace_project(
    project_id: str,
    body: WorkspaceProjectArchiveWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceProjectResponse:
    return await _set_workspace_project_archived(project_id, True, body.expected_revision, db)


@router.post("/projects/{project_id}/restore", response_model=WorkspaceProjectResponse)
async def restore_workspace_project(
    project_id: str,
    body: WorkspaceProjectArchiveWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceProjectResponse:
    return await _set_workspace_project_archived(project_id, False, body.expected_revision, db)


@router.post("/projects", response_model=WorkspaceProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_project(
    body: WorkspaceProjectWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceProjectResponse:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Project name must not be blank.")
    project = WorkspaceProjectModel(
        **({"id": str(body.id)} if body.id else {}),
        name=name,
        name_key=name.casefold(),
        subtitle=body.subtitle.strip(),
    )
    db.add(project)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A project with this name or ID already exists.") from exc
    await db.refresh(project)
    return WorkspaceProjectResponse.model_validate(project, from_attributes=True)


@router.get("/search", response_model=list[WorkspaceSearchResult])
async def search_workspace(
    response: Response,
    query: str = Query(min_length=1, max_length=200),
    project_name: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=25, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceSearchResult]:
    """Search persisted workspace object titles and text without exposing metadata blobs."""
    normalized = " ".join(query.split())
    if not normalized:
        raise HTTPException(status_code=422, detail="Search query must not be blank.")
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    filters = [or_(
        WorkspaceObjectModel.title.ilike(pattern, escape="\\"),
        WorkspaceObjectModel.content.ilike(pattern, escape="\\"),
        (WorkspaceObjectModel.object_type == "file_reference") & or_(
            WorkspaceObjectModel.metadata_json["detail"].as_string().ilike(pattern, escape="\\"),
            WorkspaceObjectModel.metadata_json["collection"].as_string().ilike(pattern, escape="\\"),
            WorkspaceObjectModel.metadata_json["tags"].cast(String).ilike(pattern, escape="\\"),
        ),
    )]
    if project_name:
        personal_project_links = select(WorkspaceObjectProjectLinkModel.object_id).where(
            WorkspaceObjectProjectLinkModel.project_name == project_name
        )
        filters.append(or_(
            WorkspaceObjectModel.project_name == project_name,
            WorkspaceObjectModel.project_name.is_(None) & WorkspaceObjectModel.id.in_(personal_project_links),
        ))
    normalized_lower = normalized.lower()
    rank = case(
        (func.lower(WorkspaceObjectModel.title) == normalized_lower, 0),
        (func.lower(WorkspaceObjectModel.title).like(f"{escaped.lower()}%", escape="\\"), 1),
        (func.lower(WorkspaceObjectModel.title).like(pattern.lower(), escape="\\"), 2),
        else_=3,
    )
    if cursor is not None:
        cursor_rank, cursor_updated_at, cursor_id = _decode_workspace_search_cursor(cursor)
        filters.append(or_(
            rank > cursor_rank,
            and_(
                rank == cursor_rank,
                or_(
                    WorkspaceObjectModel.updated_at < cursor_updated_at,
                    and_(WorkspaceObjectModel.updated_at == cursor_updated_at, WorkspaceObjectModel.id > cursor_id),
                ),
            ),
        ))
    result = await db.execute(
        select(WorkspaceObjectModel, rank.label("search_rank"))
        .where(*filters)
        .order_by(rank, WorkspaceObjectModel.updated_at.desc(), WorkspaceObjectModel.id)
        .limit(limit + 1)
    )
    rows = list(result.all())
    if len(rows) > limit:
        last_item, last_rank = rows[limit - 1]
        response.headers["X-Next-Cursor"] = _encode_workspace_search_cursor(int(last_rank), last_item)
        rows = rows[:limit]
    items: list[WorkspaceSearchResult] = []
    for item, _search_rank in rows:
        content = item.content or ""
        metadata = item.metadata_json if isinstance(item.metadata_json, dict) else {}
        searchable_content = content
        if item.object_type == "file_reference" and normalized.casefold() not in searchable_content.casefold():
            raw_tags = metadata.get("tags")
            tags = [tag for tag in raw_tags if isinstance(tag, str)] if isinstance(raw_tags, list) else []
            safe_metadata = [metadata.get("detail"), " ".join(tags), metadata.get("collection")]
            searchable_content = next((value for value in safe_metadata if isinstance(value, str) and normalized.casefold() in value.casefold()), content)
        match_at = searchable_content.casefold().find(normalized.casefold())
        if match_at >= 0:
            start = max(0, match_at - 70)
            excerpt = ("…" if start else "") + searchable_content[start : match_at + len(normalized) + 110].strip()
            if start + len(excerpt) < len(searchable_content):
                excerpt += "…"
        else:
            excerpt = searchable_content[:180].strip() + ("…" if len(searchable_content) > 180 else "")
        items.append(WorkspaceSearchResult(
            object_id=item.id,
            object_type=item.object_type,
            title=item.title or "(untitled)",
            excerpt=excerpt,
            project_name=item.project_name,
            created_by=item.created_by,
            verification_status=(
                metadata.get("verification_status")
                if item.object_type == "research_claim" and isinstance(metadata.get("verification_status"), str)
                else None
            ),
            related_object_id=(
                metadata.get("study_session_id")
                if item.object_type == "study_card"
                and isinstance(metadata.get("study_session_id"), str)
                and len(metadata["study_session_id"]) <= 36
                else None
            ),
            updated_at=item.updated_at,
        ))
    return items

MAX_EXECUTION_GRAPH_RUNS = 100
MAX_EXECUTION_GRAPH_EVENTS = 3_000
MAX_WORKSPACE_GRAPH_OBJECTS_PER_PAGE = 500
MAX_WORKSPACE_GRAPH_EDGES_PER_PAGE = 500

EXECUTION_GRAPH_EVENT_TYPES = {
    "model_selected", "reasoning_effort_selected", "fallback_considered", "fallback_blocked", "context_compiled",
    "delegation_started", "delegation_completed", "tool_requested", "tool_executed",
    "approval_requested", "approval_granted", "approval_rejected", "response_generated",
    "automation_triggered", "run_completed", "run_failed", "run_cancelled",
}


def _safe_execution_event(event: RunEventModel) -> WorkspaceExecutionEventResponse:
    """Project operational trace and routing provenance without exposing private payloads."""
    payload = event.payload if isinstance(event.payload, dict) else {}
    event_type = event.event_type
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    error_metadata = (
        safe_operational_error_metadata(result.get("metadata"))
        if result.get("success") is False
        else {}
    )
    raw_tool_name = payload.get("tool") or payload.get("tool_name")
    tool_name = raw_tool_name if isinstance(raw_tool_name, str) else None
    step = payload.get("step")

    def safe_text(key: str) -> str | None:
        value = payload.get(key)
        return value[:120] if isinstance(value, str) else None

    bounds = payload.get("configured_bounds")
    reasoning_bounds = None
    if event_type == "reasoning_effort_selected" and isinstance(bounds, dict):
        reasoning_bounds = {
            key: bounds[key][:32] if isinstance(bounds.get(key), str) else None
            for key in ("min", "max")
        }
    context_objects = []
    raw_context_objects = payload.get("objects") if event_type == "context_compiled" else None
    if isinstance(raw_context_objects, list):
        for item in raw_context_objects[:128]:
            if not isinstance(item, dict):
                continue
            object_id = item.get("object_id")
            object_type = item.get("object_type")
            if not isinstance(object_id, str) or not object_id or len(object_id) > 256:
                continue
            if not isinstance(object_type, str) or not object_type or len(object_type) > 64:
                continue
            raw_source_ids = item.get("source_object_ids")
            source_object_ids = []
            if isinstance(raw_source_ids, list):
                source_object_ids = list(dict.fromkeys(
                    value for value in raw_source_ids[:128]
                    if isinstance(value, str) and value and len(value) <= 256
                ))
            raw_sections = item.get("selected_sections")
            selected_sections = None
            if isinstance(raw_sections, dict):
                selected_sections = {
                    key: value for key, value in list(raw_sections.items())[:32]
                    if isinstance(key, str) and key and len(key) <= 64
                    and (value is None or isinstance(value, bool))
                }
            context_objects.append({
                "object_id": object_id,
                "object_type": object_type,
                "selected_by_user": item.get("selected_by_user") if isinstance(item.get("selected_by_user"), bool) else False,
                "source_object_ids": source_object_ids,
                "selected_sections": selected_sections,
            })
    context_estimated_tokens = payload.get("estimated_tokens")
    if not isinstance(context_estimated_tokens, int) or isinstance(context_estimated_tokens, bool) or context_estimated_tokens < 0:
        context_estimated_tokens = None

    profile_version = payload.get("profile_version")
    return WorkspaceExecutionEventResponse(
        id=event.id,
        event_type=event_type,
        created_at=event.created_at,
        agent_role=safe_text("agent_role"),
        specialist=safe_text("specialist"),
        provider=safe_text("provider"),
        model=safe_text("model"),
        tool_name=tool_name,
        tool_call_id=safe_text("tool_call_id"),
        child_run_id=safe_text("child_run_id"),
        status=(safe_text("status"))
        or ("completed" if result.get("success") is True else "failed" if result.get("success") is False else None),
        success=result.get("success") if isinstance(result.get("success"), bool) else None,
        error_category=safe_text("error_category"),
        error_code=error_metadata.get("error_code"),
        failed_providers=error_metadata.get("failed_providers", []),
        risk_level=safe_text("risk_level"),
        step=step if isinstance(step, int) and not isinstance(step, bool) else None,
        task_type=safe_text("task_type") if event_type == "model_selected" else None,
        profile_id=safe_text("profile_id") if event_type == "model_selected" else None,
        profile_version=profile_version if event_type == "model_selected" and isinstance(profile_version, int) and not isinstance(profile_version, bool) else None,
        winning_scope=safe_text("winning_scope") if event_type == "model_selected" else None,
        privacy=safe_text("privacy") if event_type == "model_selected" else None,
        fallback_policy=safe_text("fallback_policy") if event_type in {"model_selected", "fallback_considered"} else safe_text("policy") if event_type == "fallback_blocked" else None,
        selection_reason=safe_text("selection_reason") if event_type == "model_selected" else None,
        reasoning_policy=safe_text("policy_mode") if event_type == "reasoning_effort_selected" else None,
        reasoning_bounds=reasoning_bounds,
        selected_effort=safe_text("selected_effort") if event_type == "reasoning_effort_selected" else None,
        primary_provider=safe_text("primary_provider") if event_type == "fallback_considered" else None,
        selected_provider=safe_text("selected_provider") if event_type == "fallback_considered" else None,
        candidate_model=safe_text("candidate_model") if event_type == "fallback_considered" else None,
        privacy_boundary=safe_text("privacy_boundary") if event_type == "fallback_blocked" else None,
        error_type=safe_text("error_type") if event_type == "fallback_blocked" else None,
        proposed_provider=safe_text("proposed_provider") if event_type == "fallback_blocked" else None,
        proposed_model=safe_text("proposed_model") if event_type == "fallback_blocked" else None,
        trigger_event_id=safe_text("trigger_event_id") if event_type == "automation_triggered" else None,
        automation_id=safe_text("automation_id") if event_type == "automation_triggered" else None,
        automation_name=safe_text("automation_name") if event_type == "automation_triggered" else None,
        context_objects=context_objects,
        context_estimated_tokens=context_estimated_tokens if event_type == "context_compiled" else None,
        context_privacy_requirement=safe_text("privacy_requirement") if event_type == "context_compiled" else None,
    )


async def _lock_project_graph(db: AsyncSession, project_name: str) -> None:
    """Serialize graph writes per project on PostgreSQL before validating invariants."""
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:project_name))"), {"project_name": project_name})


def _object_response(item: WorkspaceObjectModel) -> WorkspaceObjectResponse:
    return WorkspaceObjectResponse(
        id=item.id,
        project_name=item.project_name,
        session_id=item.session_id,
        source_message_id=item.source_message_id,
        object_type=item.object_type,
        created_by=item.created_by,
        title=item.title,
        content=item.content,
        metadata_json=item.metadata_json or {},
        revision=item.revision,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _compare_and_swap_workspace_object(
    db: AsyncSession,
    item: WorkspaceObjectModel,
    *,
    expected_revision: int,
    title: str,
    content: str,
    metadata_json: dict[str, object],
    conflict_code: str | None = None,
    conflict_message: str = "Workspace object changed since it was loaded.",
) -> WorkspaceObjectModel:
    object_id = item.id
    result = await db.execute(
        sa_update(WorkspaceObjectModel)
        .where(
            WorkspaceObjectModel.id == object_id,
            WorkspaceObjectModel.revision == expected_revision,
        )
        .values(
            title=title,
            content=content,
            metadata_json=metadata_json,
            revision=WorkspaceObjectModel.revision + 1,
            updated_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        current_revision = await db.scalar(
            select(WorkspaceObjectModel.revision).where(WorkspaceObjectModel.id == object_id)
        )
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Workspace object not found.")
        detail = {"message": conflict_message, "current_revision": current_revision}
        if conflict_code is not None:
            detail["code"] = conflict_code
        raise HTTPException(
            status_code=409,
            detail=detail,
        )
    await db.flush()
    await db.refresh(item)
    return item


def _edge_response(edge: WorkspaceEdgeModel) -> WorkspaceEdgeResponse:
    return WorkspaceEdgeResponse(
        id=edge.id,
        project_name=edge.project_name,
        source_object_id=edge.source_object_id,
        target_object_id=edge.target_object_id,
        relation_type=edge.relation_type,
        edge_family=edge.edge_family,
        created_by=edge.created_by,
        metadata_json=edge.metadata_json or {},
        created_at=edge.created_at,
    )


async def _get_project_objects(db: AsyncSession, project_name: str) -> list[WorkspaceObjectModel]:
    result = await db.execute(
        select(WorkspaceObjectModel)
        .where(WorkspaceObjectModel.project_name == project_name)
        .order_by(WorkspaceObjectModel.created_at, WorkspaceObjectModel.id)
    )
    return list(result.scalars())


async def _would_create_context_cycle(
    db: AsyncSession,
    project_name: str,
    source_ids: list[str],
    target_id: str,
) -> bool:
    """Return true if target reaches any proposed source in the existing context graph."""
    if not source_ids:
        return False
    statement = text("""
        WITH RECURSIVE reachable(object_id) AS (
            SELECT :target_id
            UNION
            SELECT edge.target_object_id
            FROM workspace_edges AS edge
            JOIN reachable ON edge.source_object_id = reachable.object_id
            WHERE edge.project_name = :project_name
              AND edge.edge_family = 'context'
        )
        SELECT EXISTS (
            SELECT 1 FROM reachable WHERE object_id IN :source_ids
        )
    """).bindparams(bindparam("source_ids", expanding=True))
    result = await db.execute(statement, {
        "project_name": project_name,
        "target_id": target_id,
        "source_ids": source_ids,
    })
    return bool(result.scalar())


async def _project_objects_by_ids(db: AsyncSession, project_name: str, ids: list[str]) -> dict[str, WorkspaceObjectModel]:
    if not ids:
        return {}
    result = await db.execute(
        select(WorkspaceObjectModel).where(
            WorkspaceObjectModel.project_name == project_name,
            WorkspaceObjectModel.id.in_(set(ids)),
        )
    )
    objects = {item.id: item for item in result.scalars()}
    linked = await db.execute(
        select(WorkspaceObjectModel)
        .join(WorkspaceObjectProjectLinkModel, WorkspaceObjectProjectLinkModel.object_id == WorkspaceObjectModel.id)
        .where(
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type.in_({"manual_note", "file_reference", "study_session", "study_card"}),
            WorkspaceObjectProjectLinkModel.project_name == project_name,
            WorkspaceObjectModel.id.in_(set(ids) - set(objects)),
        )
    )
    objects.update({item.id: item for item in linked.scalars()})
    return objects


async def _workspace_note_responses(
    db: AsyncSession,
    items: list[WorkspaceObjectModel],
) -> list[WorkspaceNoteResponse]:
    ids = [item.id for item in items]
    links = await db.execute(
        select(WorkspaceObjectProjectLinkModel.object_id, WorkspaceObjectProjectLinkModel.project_name)
        .where(WorkspaceObjectProjectLinkModel.object_id.in_(ids))
        .order_by(WorkspaceObjectProjectLinkModel.project_name)
    ) if ids else None
    projects_by_note: dict[str, list[str]] = {object_id: [] for object_id in ids}
    if links is not None:
        for object_id, project_name in links:
            projects_by_note[object_id].append(project_name)
    responses: list[WorkspaceNoteResponse] = []
    for item in items:
        metadata = item.metadata_json or {}
        tags = metadata.get("tags", [])
        responses.append(WorkspaceNoteResponse(
            id=item.id,
            title=item.title,
            body=item.content,
            tags=[tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else [],
            project_names=projects_by_note[item.id],
            pinned=metadata.get("pinned") is True,
            privacy_policy=metadata.get("privacy_policy") if isinstance(metadata.get("privacy_policy"), str) else None,
            revision=item.revision,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ))
    return responses


async def _workspace_note_response(db: AsyncSession, item: WorkspaceObjectModel) -> WorkspaceNoteResponse:
    return (await _workspace_note_responses(db, [item]))[0]


async def _workspace_library_responses(
    db: AsyncSession,
    items: list[WorkspaceObjectModel],
) -> list[WorkspaceLibraryReferenceResponse]:
    ids = [item.id for item in items]
    links = await db.execute(
        select(WorkspaceObjectProjectLinkModel.object_id, WorkspaceObjectProjectLinkModel.project_name)
        .where(WorkspaceObjectProjectLinkModel.object_id.in_(ids))
        .order_by(WorkspaceObjectProjectLinkModel.project_name)
    ) if ids else None
    projects_by_item: dict[str, list[str]] = {object_id: [] for object_id in ids}
    if links is not None:
        for object_id, project_name in links:
            projects_by_item[object_id].append(project_name)
    responses: list[WorkspaceLibraryReferenceResponse] = []
    for item in items:
        metadata = item.metadata_json or {}
        tags = metadata.get("tags", [])
        responses.append(WorkspaceLibraryReferenceResponse(
            id=item.id,
            name=item.title,
            kind=metadata.get("kind", "FILE"),
            collection=metadata.get("collection", "Reference"),
            detail=metadata.get("detail", ""),
            tags=[tag for tag in tags if isinstance(tag, str)] if isinstance(tags, list) else [],
            project_names=projects_by_item[item.id],
            size=metadata.get("size") if isinstance(metadata.get("size"), int) else None,
            mime_type=metadata.get("mime_type") if isinstance(metadata.get("mime_type"), str) else None,
            revision=item.revision,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ))
    return responses


def _library_reference_metadata(body: WorkspaceLibraryReferenceWrite) -> dict[str, object]:
    tags = list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip()))
    if any(len(tag) > 64 for tag in tags):
        raise HTTPException(status_code=422, detail="Library tags must be 64 characters or fewer.")
    return {
        "kind": body.kind,
        "collection": body.collection,
        "detail": body.detail,
        "tags": tags,
        "size": body.size,
        "mime_type": body.mime_type,
        "storage_location": "browser_local",
    }


def _note_metadata(body: WorkspaceNoteWrite) -> dict[str, object]:
    tags = list(dict.fromkeys(tag.strip() for tag in body.tags if tag.strip()))
    if any(len(tag) > 64 for tag in tags):
        raise HTTPException(status_code=422, detail="Note tags must be 64 characters or fewer.")
    return {"tags": tags, "pinned": body.pinned}


async def _sync_workspace_note_links(
    db: AsyncSession,
    item: WorkspaceObjectModel,
    project_names: list[str],
) -> None:
    names = list(dict.fromkeys(name.strip() for name in project_names if name.strip()))
    if any(len(name) > 128 for name in names):
        raise HTTPException(status_code=422, detail="Project names must be 128 characters or fewer.")
    result = await db.execute(
        select(WorkspaceObjectProjectLinkModel).where(WorkspaceObjectProjectLinkModel.object_id == item.id)
    )
    existing = {link.project_name: link for link in result.scalars()}
    removed = set(existing) - set(names)
    for name in removed:
        await db.execute(
            sa_delete(WorkspaceEdgeModel).where(
                WorkspaceEdgeModel.project_name == name,
                (WorkspaceEdgeModel.source_object_id == item.id) | (WorkspaceEdgeModel.target_object_id == item.id),
            )
        )
        await db.delete(existing[name])
    for name in names:
        if name not in existing:
            db.add(WorkspaceObjectProjectLinkModel(object_id=item.id, project_name=name))


@router.post(
    "/projects/{project_name}/context/preview",
    response_model=WorkspaceContextPreviewResponse,
)
async def preview_workspace_context(
    project_name: str,
    body: WorkspaceContextPreviewRequest,
    db: AsyncSession = Depends(get_db),
    tool_registry: ToolRegistry = Depends(get_tool_registry),
) -> WorkspaceContextPreviewResponse:
    """Compile selected project context for inspection without invoking a model or writing data."""
    compiled = await WorkspaceContextCompiler(db).compile(project_name, body.selected_object_ids)
    _model_caps, tool_capabilities, capability_flags = split_context_capabilities(compiled.required_capabilities)
    available_capabilities: list[str] = []
    missing_capabilities: list[str] = []
    if tool_capabilities:
        try:
            tool_registry.resolve_capabilities(tool_capabilities, privacy_requirement=compiled.privacy_requirement)
            available_capabilities = tool_capabilities
        except UnresolvedCapabilitiesError as exc:
            missing_capabilities = exc.capabilities
            available_capabilities = sorted(set(tool_capabilities) - set(missing_capabilities))
    return WorkspaceContextPreviewResponse.model_validate({
        **compiled.model_dump(),
        "available_capabilities": available_capabilities,
        "missing_capabilities": missing_capabilities,
        "requires_tools": compiled.requires_tools or capability_flags["requires_tools"] or bool(tool_capabilities),
        "requires_vision": compiled.requires_vision or capability_flags["requires_vision"],
        "requires_structured_output": compiled.requires_structured_output or capability_flags["requires_structured_output"],
        "requires_long_context": compiled.requires_long_context or capability_flags["requires_long_context"],
    })




async def _project_execution_history(
    db: AsyncSession,
    project_name: str,
    execution_cursor: str | None,
    execution_page_size: int,
) -> WorkspaceExecutionHistoryResponse:
    project_session_ids = select(SessionModel.id).where(SessionModel.project_name == project_name)
    cursor_created_at: datetime | None = None
    cursor_run_id: str | None = None
    if execution_cursor:
        try:
            encoded = execution_cursor + "=" * (-len(execution_cursor) % 4)
            cursor_created_at_text, cursor_run_id = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
            cursor_created_at = datetime.fromisoformat(cursor_created_at_text)
            if cursor_created_at.tzinfo is None:
                cursor_created_at = cursor_created_at.replace(tzinfo=timezone.utc)
            if not isinstance(cursor_run_id, str) or not cursor_run_id or len(cursor_run_id) > 36:
                raise ValueError("invalid run ID")
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail="Invalid execution history cursor.")

    runs: list[RunModel] = []
    run_query = select(RunModel).where(RunModel.session_id.in_(project_session_ids))
    if cursor_created_at is not None and cursor_run_id is not None:
        run_query = run_query.where(or_(
            RunModel.created_at < cursor_created_at,
            (RunModel.created_at == cursor_created_at) & (RunModel.id < cursor_run_id),
        ))
    run_result = await db.execute(
        run_query.order_by(RunModel.created_at.desc(), RunModel.id.desc()).limit(execution_page_size + 1)
    )
    runs = list(run_result.scalars())
    runs_truncated = len(runs) > execution_page_size
    runs = runs[:execution_page_size]
    execution_next_cursor = None
    if runs_truncated and runs:
        oldest_run = runs[-1]
        cursor_payload = json.dumps([oldest_run.created_at.isoformat(), oldest_run.id], separators=(",", ":"))
        execution_next_cursor = base64.urlsafe_b64encode(cursor_payload.encode("utf-8")).decode("ascii").rstrip("=")

    events_truncated = False
    execution_traces: list[WorkspaceExecutionTraceResponse] = []
    if runs:
        run_ids = [run.id for run in runs]
        event_result = await db.execute(
            select(RunEventModel)
            .where(
                RunEventModel.run_id.in_(run_ids),
                RunEventModel.event_type.in_(EXECUTION_GRAPH_EVENT_TYPES),
            )
            .order_by(RunEventModel.created_at.desc(), RunEventModel.id.desc())
            .limit(MAX_EXECUTION_GRAPH_EVENTS + 1)
        )
        event_rows = list(event_result.scalars())
        events_truncated = len(event_rows) > MAX_EXECUTION_GRAPH_EVENTS
        events_by_run: dict[str, list[WorkspaceExecutionEventResponse]] = {run_id: [] for run_id in run_ids}
        for event in event_rows[:MAX_EXECUTION_GRAPH_EVENTS]:
            events_by_run[event.run_id].append(_safe_execution_event(event))
        for run_events in events_by_run.values():
            run_events.reverse()

        turn_result = await db.execute(
            select(WorkspaceObjectModel.id, WorkspaceObjectModel.metadata_json)
            .where(
                WorkspaceObjectModel.project_name == project_name,
                WorkspaceObjectModel.object_type == "conversation_turn",
                WorkspaceObjectModel.metadata_json["run_id"].as_string().in_(run_ids),
            )
        )
        turn_objects_by_run: dict[str, dict[str, str]] = {}
        for object_id, metadata in turn_result:
            metadata = metadata if isinstance(metadata, dict) else {}
            run_id = metadata.get("run_id")
            role = metadata.get("role")
            if isinstance(run_id, str) and role in {"user", "assistant"}:
                turn_objects_by_run.setdefault(run_id, {})[role] = object_id
        for run in reversed(runs):
            events = events_by_run[run.id]
            if not events:
                continue
            turn_objects = turn_objects_by_run.get(run.id, {})
            execution_traces.append(WorkspaceExecutionTraceResponse(
                run_id=run.id,
                parent_run_id=run.parent_run_id,
                session_id=run.session_id,
                user_object_id=turn_objects.get("user"),
                response_object_id=turn_objects.get("assistant"),
                events=events,
            ))
    return WorkspaceExecutionHistoryResponse(
        execution_traces=execution_traces,
        execution_history_truncated=events_truncated,
        execution_next_cursor=execution_next_cursor,
    )


@router.get("/projects/{project_name}/graph", response_model=WorkspaceGraphResponse)
async def get_workspace_graph(
    project_name: str,
    execution_cursor: str | None = Query(default=None, max_length=512),
    execution_page_size: int = Query(default=MAX_EXECUTION_GRAPH_RUNS, ge=1, le=MAX_EXECUTION_GRAPH_RUNS),
    object_cursor: str | None = Query(default=None, max_length=512),
    object_page_size: int = Query(default=250, ge=1, le=MAX_WORKSPACE_GRAPH_OBJECTS_PER_PAGE),
    object_types: list[str] | None = Query(default=None, max_length=16),
    newest_first: bool = Query(default=False),
    objects_exhausted: bool = Query(default=False),
    edge_cursor: str | None = Query(default=None, max_length=512),
    edge_page_size: int = Query(default=250, ge=1, le=MAX_WORKSPACE_GRAPH_EDGES_PER_PAGE),
    edge_families: list[str] | None = Query(default=None, max_length=4),
    edges_exhausted: bool = Query(default=False),
    include_project_state: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceGraphResponse:
    supported_edge_families = {"semantic", "context", "execution", "provenance"}
    if edge_families and not set(edge_families) <= supported_edge_families:
        raise HTTPException(status_code=422, detail="Unsupported workspace edge family filter.")

    linked_ids = select(WorkspaceObjectProjectLinkModel.object_id).where(
        WorkspaceObjectProjectLinkModel.project_name == project_name
    )
    visible_filter = or_(
        WorkspaceObjectModel.project_name == project_name,
        and_(
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type.in_({"manual_note", "file_reference", "study_session", "study_card"}),
            WorkspaceObjectModel.id.in_(linked_ids),
        ),
    )
    if objects_exhausted and object_cursor is not None:
        raise HTTPException(status_code=422, detail="Exhausted workspace graph objects cannot include a cursor.")
    if edges_exhausted and edge_cursor is not None:
        raise HTTPException(status_code=422, detail="Exhausted workspace graph edges cannot include a cursor.")

    object_query = select(WorkspaceObjectModel).where(visible_filter)
    if object_types:
        object_query = object_query.where(WorkspaceObjectModel.object_type.in_(set(object_types)))
    if objects_exhausted:
        object_rows = []
    else:
        if object_cursor is not None:
            cursor_created_at, cursor_object_id = decode_timestamp_id_cursor(object_cursor)
            if newest_first:
                object_query = object_query.where(or_(
                    WorkspaceObjectModel.created_at < cursor_created_at,
                    (WorkspaceObjectModel.created_at == cursor_created_at) & (WorkspaceObjectModel.id < cursor_object_id),
                ))
            else:
                object_query = object_query.where(or_(
                    WorkspaceObjectModel.created_at > cursor_created_at,
                    (WorkspaceObjectModel.created_at == cursor_created_at) & (WorkspaceObjectModel.id > cursor_object_id),
                ))
        object_order = (
            (WorkspaceObjectModel.created_at.desc(), WorkspaceObjectModel.id.desc())
            if newest_first else (WorkspaceObjectModel.created_at, WorkspaceObjectModel.id)
        )
        object_result = await db.execute(
            object_query.order_by(*object_order).limit(object_page_size + 1)
        )
        object_rows = list(object_result.scalars())
    objects_truncated = len(object_rows) > object_page_size
    objects = object_rows[:object_page_size]
    objects_next_cursor = encode_timestamp_id_cursor(objects[-1].created_at, objects[-1].id) if objects_truncated and objects else None

    edge_query = select(WorkspaceEdgeModel).where(
        WorkspaceEdgeModel.project_name == project_name,
        WorkspaceEdgeModel.source_object_id.in_(select(WorkspaceObjectModel.id).where(visible_filter)),
        WorkspaceEdgeModel.target_object_id.in_(select(WorkspaceObjectModel.id).where(visible_filter)),
    )
    if edge_families:
        edge_query = edge_query.where(WorkspaceEdgeModel.edge_family.in_(set(edge_families)))
    if edges_exhausted:
        edges = []
        edges_next_cursor = None
    else:
        if edge_cursor is not None:
            cursor_created_at, cursor_edge_id = decode_timestamp_id_cursor(edge_cursor)
            if newest_first:
                edge_query = edge_query.where(or_(
                    WorkspaceEdgeModel.created_at < cursor_created_at,
                    (WorkspaceEdgeModel.created_at == cursor_created_at) & (WorkspaceEdgeModel.id < cursor_edge_id),
                ))
            else:
                edge_query = edge_query.where(or_(
                    WorkspaceEdgeModel.created_at > cursor_created_at,
                    (WorkspaceEdgeModel.created_at == cursor_created_at) & (WorkspaceEdgeModel.id > cursor_edge_id),
                ))
        edge_order = (
            (WorkspaceEdgeModel.created_at.desc(), WorkspaceEdgeModel.id.desc())
            if newest_first else (WorkspaceEdgeModel.created_at, WorkspaceEdgeModel.id)
        )
        edge_result = await db.execute(
            edge_query.order_by(*edge_order).limit(edge_page_size + 1)
        )
        edge_rows = list(edge_result.scalars())
        edges_truncated = len(edge_rows) > edge_page_size
        edges = edge_rows[:edge_page_size]
        edges_next_cursor = encode_timestamp_id_cursor(edges[-1].created_at, edges[-1].id) if edges_truncated and edges else None
    if include_project_state:
        layout = await db.get(WorkspaceLayoutModel, project_name)
        execution_history = await _project_execution_history(db, project_name, execution_cursor, execution_page_size)
    else:
        layout = None
        execution_history = WorkspaceExecutionHistoryResponse()
    return WorkspaceGraphResponse(
        project_name=project_name,
        objects=[_object_response(item) for item in objects],
        edges=[_edge_response(edge) for edge in edges],
        layout=WorkspaceLayoutResponse(
            project_name=project_name,
            layout=layout.layout_json if layout else {},
            revision=layout.revision if layout else 0,
            updated_at=layout.updated_at if layout else None,
        ),
        objects_next_cursor=objects_next_cursor,
        edges_next_cursor=edges_next_cursor,
        execution_traces=execution_history.execution_traces,
        execution_history_truncated=execution_history.execution_history_truncated,
        execution_next_cursor=execution_history.execution_next_cursor,
    )


@router.get("/projects/{project_name}/execution", response_model=WorkspaceExecutionHistoryResponse)
async def get_workspace_execution_history(
    project_name: str,
    execution_cursor: str | None = Query(default=None, max_length=512),
    execution_page_size: int = Query(default=MAX_EXECUTION_GRAPH_RUNS, ge=1, le=MAX_EXECUTION_GRAPH_RUNS),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceExecutionHistoryResponse:
    """Return one sanitized execution-history page without loading workspace objects or layout."""
    return await _project_execution_history(db, project_name, execution_cursor, execution_page_size)


@router.get("/notes", response_model=list[WorkspaceNoteResponse])
async def list_personal_workspace_notes(
    response: Response,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int = Query(default=100, ge=1, le=MAX_WORKSPACE_COLLECTION_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceNoteResponse]:
    query = select(WorkspaceObjectModel).where(
        WorkspaceObjectModel.project_name.is_(None),
        WorkspaceObjectModel.object_type == "manual_note",
        WorkspaceObjectModel.created_by == "user",
    )
    if cursor is not None:
        query = query.where(_descending_timestamp_cursor_filter(
            WorkspaceObjectModel.updated_at, WorkspaceObjectModel.id, cursor,
        ))
    result = await db.execute(
        query.order_by(WorkspaceObjectModel.updated_at.desc(), WorkspaceObjectModel.id).limit(page_size + 1)
    )
    items = _set_next_cursor(response, list(result.scalars()), page_size, "updated_at")
    return await _workspace_note_responses(db, items)


@router.get("/notes/{note_id}", response_model=WorkspaceNoteResponse)
async def get_personal_workspace_note(note_id: str, db: AsyncSession = Depends(get_db)) -> WorkspaceNoteResponse:
    item = await db.get(WorkspaceObjectModel, note_id)
    if (
        item is None
        or item.project_name is not None
        or item.object_type != "manual_note"
        or item.created_by != "user"
    ):
        raise HTTPException(status_code=404, detail="Personal workspace note not found.")
    return await _workspace_note_response(db, item)


@router.post("/notes", response_model=WorkspaceNoteResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_workspace_note(
    body: WorkspaceNoteWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteResponse:
    metadata = _note_metadata(body)
    item = WorkspaceObjectModel(
        project_name=None,
        object_type="manual_note",
        created_by="user",
        title=body.title,
        content=body.body,
        metadata_json={
            **metadata,
            **({"privacy_policy": body.privacy_policy} if body.privacy_policy is not None else {}),
        },
    )
    db.add(item)
    await db.flush()
    await _sync_workspace_note_links(db, item, body.project_names)
    await db.commit()
    await db.refresh(item)
    return await _workspace_note_response(db, item)


@router.put("/notes/{note_id}", response_model=WorkspaceNoteResponse)
async def update_personal_workspace_note(
    note_id: str,
    body: WorkspaceNoteWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceNoteResponse:
    item = await db.get(WorkspaceObjectModel, note_id)
    if (
        item is None
        or item.project_name is not None
        or item.object_type != "manual_note"
        or item.created_by != "user"
    ):
        raise HTTPException(status_code=404, detail="Personal workspace note not found.")
    if body.expected_revision is None:
        raise HTTPException(status_code=422, detail="expected_revision is required when updating a saved Note.")
    metadata = {**(item.metadata_json or {}), **_note_metadata(body)}
    if "privacy_policy" in body.model_fields_set:
        if body.privacy_policy is None:
            metadata.pop("privacy_policy", None)
        else:
            metadata["privacy_policy"] = body.privacy_policy
    await _compare_and_swap_workspace_object(
        db,
        item,
        expected_revision=body.expected_revision,
        title=body.title,
        content=body.body,
        metadata_json=metadata,
    )
    await _sync_workspace_note_links(db, item, body.project_names)
    await db.commit()
    await db.refresh(item)
    return await _workspace_note_response(db, item)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_workspace_note(
    note_id: str,
    expected_revision: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
) -> None:
    item = await db.get(WorkspaceObjectModel, note_id)
    if (
        item is None
        or item.project_name is not None
        or item.object_type != "manual_note"
        or item.created_by != "user"
    ):
        raise HTTPException(status_code=404, detail="Personal workspace note not found.")

    result = await db.execute(
        sa_delete(WorkspaceObjectModel)
        .where(
            WorkspaceObjectModel.id == note_id,
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type == "manual_note",
            WorkspaceObjectModel.created_by == "user",
            WorkspaceObjectModel.revision == expected_revision,
        )
        .returning(WorkspaceObjectModel.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        current_revision = await db.scalar(
            select(WorkspaceObjectModel.revision).where(WorkspaceObjectModel.id == note_id)
        )
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Personal workspace note not found.")
        raise HTTPException(
            status_code=409,
            detail={"message": "Workspace note changed since it was loaded.", "current_revision": current_revision},
        )
    await db.commit()


@router.get("/library", response_model=list[WorkspaceLibraryReferenceResponse])
async def list_personal_library_references(
    response: Response,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int = Query(default=100, ge=1, le=MAX_WORKSPACE_COLLECTION_PAGE_SIZE),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    project_name: str | None = Query(default=None, max_length=128),
    unlinked_project_name: str | None = Query(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceLibraryReferenceResponse]:
    query = select(WorkspaceObjectModel).where(
        WorkspaceObjectModel.project_name.is_(None),
        WorkspaceObjectModel.object_type == "file_reference",
        WorkspaceObjectModel.created_by == "user",
    )
    if project_name is not None:
        normalized_project = project_name.strip()
        if not normalized_project:
            raise HTTPException(status_code=422, detail="Project name must not be blank.")
        linked_object_ids = select(WorkspaceObjectProjectLinkModel.object_id).where(
            WorkspaceObjectProjectLinkModel.project_name == normalized_project
        )
        query = query.where(WorkspaceObjectModel.id.in_(linked_object_ids))
    if unlinked_project_name is not None:
        normalized_project = unlinked_project_name.strip()
        if not normalized_project:
            raise HTTPException(status_code=422, detail="Project name must not be blank.")
        linked_object_ids = select(WorkspaceObjectProjectLinkModel.object_id).where(
            WorkspaceObjectProjectLinkModel.project_name == normalized_project
        )
        query = query.where(WorkspaceObjectModel.id.not_in(linked_object_ids))
    if q is not None:
        normalized = " ".join(q.split())
        if not normalized:
            raise HTTPException(status_code=422, detail="Search query must not be blank.")
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(or_(
            WorkspaceObjectModel.title.ilike(pattern, escape="\\"),
            WorkspaceObjectModel.metadata_json["detail"].as_string().ilike(pattern, escape="\\"),
            WorkspaceObjectModel.metadata_json["collection"].as_string().ilike(pattern, escape="\\"),
            WorkspaceObjectModel.metadata_json["tags"].cast(String).ilike(pattern, escape="\\"),
        ))
    if cursor is not None:
        query = query.where(_descending_timestamp_cursor_filter(
            WorkspaceObjectModel.updated_at, WorkspaceObjectModel.id, cursor,
        ))
    result = await db.execute(
        query.order_by(WorkspaceObjectModel.updated_at.desc(), WorkspaceObjectModel.id).limit(page_size + 1)
    )
    items = _set_next_cursor(response, list(result.scalars()), page_size, "updated_at")
    return await _workspace_library_responses(db, items)


@router.post("/library", response_model=WorkspaceLibraryReferenceResponse, status_code=status.HTTP_201_CREATED)
async def create_personal_library_reference(
    body: WorkspaceLibraryReferenceWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceLibraryReferenceResponse:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Library file name must not be blank.")
    item_id = str(body.id) if body.id else None
    if item_id and await db.get(WorkspaceObjectModel, item_id):
        raise HTTPException(status_code=409, detail="Workspace object ID already exists.")
    item = WorkspaceObjectModel(
        **({"id": item_id} if item_id else {}),
        project_name=None,
        object_type="file_reference",
        created_by="user",
        title=name,
        content="",
        metadata_json=_library_reference_metadata(body),
    )
    db.add(item)
    await db.flush()
    await _sync_workspace_note_links(db, item, body.project_names)
    await db.commit()
    await db.refresh(item)
    return (await _workspace_library_responses(db, [item]))[0]


@router.put("/library/{reference_id}", response_model=WorkspaceLibraryReferenceResponse)
async def update_personal_library_reference(
    reference_id: str,
    body: WorkspaceLibraryReferenceWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceLibraryReferenceResponse:
    item = await db.get(WorkspaceObjectModel, reference_id)
    if item is None or item.project_name is not None or item.object_type != "file_reference" or item.created_by != "user":
        raise HTTPException(status_code=404, detail="Personal Library reference not found.")
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Library file name must not be blank.")
    if body.expected_revision is None:
        raise HTTPException(status_code=422, detail="expected_revision is required when updating a Library reference.")
    await _compare_and_swap_workspace_object(
        db,
        item,
        expected_revision=body.expected_revision,
        title=name,
        content=item.content,
        metadata_json=_library_reference_metadata(body),
        conflict_code="WorkspaceLibraryRevisionConflict",
        conflict_message="Library reference changed since it was loaded.",
    )
    await _sync_workspace_note_links(db, item, body.project_names)
    await db.commit()
    await db.refresh(item)
    return (await _workspace_library_responses(db, [item]))[0]


@router.delete("/library/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_library_reference(
    reference_id: str,
    expected_revision: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
) -> None:
    item = await db.get(WorkspaceObjectModel, reference_id)
    if item is None or item.project_name is not None or item.object_type != "file_reference" or item.created_by != "user":
        raise HTTPException(status_code=404, detail="Personal Library reference not found.")
    await db.execute(
        sa_delete(WorkspaceEdgeModel).where(
            (WorkspaceEdgeModel.source_object_id == item.id) | (WorkspaceEdgeModel.target_object_id == item.id)
        )
    )
    result = await db.execute(
        sa_delete(WorkspaceObjectModel)
        .where(
            WorkspaceObjectModel.id == reference_id,
            WorkspaceObjectModel.project_name.is_(None),
            WorkspaceObjectModel.object_type == "file_reference",
            WorkspaceObjectModel.created_by == "user",
            WorkspaceObjectModel.revision == expected_revision,
        )
        .returning(WorkspaceObjectModel.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        current_revision = await db.scalar(
            select(WorkspaceObjectModel.revision).where(
                WorkspaceObjectModel.id == reference_id,
                WorkspaceObjectModel.project_name.is_(None),
                WorkspaceObjectModel.object_type == "file_reference",
                WorkspaceObjectModel.created_by == "user",
            )
        )
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Personal Library reference not found.")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WorkspaceLibraryRevisionConflict",
                "message": "Library reference changed since it was loaded.",
                "current_revision": current_revision,
            },
        )
    await db.commit()


@router.post("/projects/{project_name}/sessions/{session_id}", response_model=WorkspaceSessionResponse)
async def attach_workspace_session(
    project_name: str,
    session_id: str,
    mem_service: MemoryService = Depends(get_memory_service),
) -> WorkspaceSessionResponse:
    try:
        session = await mem_service.attach_session_to_project(session_id, project_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkspaceSessionResponse(session_id=session.id, project_name=project_name)


@router.post("/projects/{project_name}/objects", response_model=WorkspaceObjectResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_object(
    project_name: str,
    body: WorkspaceObjectCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceObjectResponse:
    await _lock_project_graph(db, project_name)
    source_ids = list(dict.fromkeys(body.source_object_ids))
    if body.object_type not in {"context_bridge", "context_set", "conversation_branch"} and source_ids:
        raise HTTPException(status_code=422, detail="Only a Context Bridge, Context Set, or Branch can declare source objects.")
    sources = await _project_objects_by_ids(db, project_name, source_ids)
    if len(sources) != len(source_ids):
        raise HTTPException(status_code=404, detail="One or more source objects were not found in this project.")

    object_id = str(body.id) if body.id else None
    if object_id and await db.get(WorkspaceObjectModel, object_id):
        raise HTTPException(status_code=409, detail="Workspace object ID already exists in this project.")

    item = WorkspaceObjectModel(
        **({"id": object_id} if object_id else {}),
        project_name=project_name,
        object_type=body.object_type,
        created_by="user",
        title=body.title,
        content=body.content,
        metadata_json=body.metadata_json,
    )
    db.add(item)
    await db.flush()

    if source_ids:
        if await _would_create_context_cycle(db, project_name, source_ids, item.id):
            await db.rollback()
            raise HTTPException(status_code=409, detail="Context Bridge would create a cycle in the context-flow graph.")
        for source_id in source_ids:
            db.add(WorkspaceEdgeModel(
                project_name=project_name,
                source_object_id=source_id,
                target_object_id=item.id,
                relation_type=(
                    "selected_into" if body.object_type == "context_set"
                    else "branches_to" if body.object_type == "conversation_branch"
                    else "bridges_to"
                ),
                edge_family="context",
                created_by="user",
                metadata_json={},
            ))

    await db.commit()
    await db.refresh(item)
    return _object_response(item)


@router.put("/projects/{project_name}/objects/{object_id}", response_model=WorkspaceObjectResponse)
async def update_workspace_object(
    project_name: str,
    object_id: str,
    body: WorkspaceObjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceObjectResponse:
    item = await db.get(WorkspaceObjectModel, object_id)
    if item is None or object_id not in await _project_objects_by_ids(db, project_name, [object_id]):
        raise HTTPException(status_code=404, detail="Workspace object not found.")
    if item.created_by != "user" or item.object_type not in {"manual_note", "context_bridge"}:
        raise HTTPException(status_code=409, detail="Only user-authored notes and bridges can be edited.")
    await _compare_and_swap_workspace_object(
        db,
        item,
        expected_revision=body.expected_revision,
        title=body.title,
        content=body.content,
        metadata_json=body.metadata_json,
    )
    await db.commit()
    return _object_response(item)


@router.delete("/projects/{project_name}/objects/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_object(
    project_name: str,
    object_id: str,
    expected_revision: int = Query(ge=1),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(WorkspaceObjectModel)
        .where(WorkspaceObjectModel.id == object_id)
        .with_for_update()
    )
    item = result.scalar_one_or_none()
    if item is None or object_id not in await _project_objects_by_ids(db, project_name, [object_id]):
        raise HTTPException(status_code=404, detail="Workspace object not found.")
    if item.revision != expected_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WorkspaceObjectRevisionConflict",
                "message": "Workspace object changed since it was loaded.",
                "current_revision": item.revision,
            },
        )
    if item.project_name is None and item.object_type in {"manual_note", "file_reference"}:
        # Claim the current revision atomically on SQLite as well as databases
        # that honor SELECT FOR UPDATE before removing this project's link.
        claimed = await db.execute(
            sa_update(WorkspaceObjectModel)
            .where(
                WorkspaceObjectModel.id == object_id,
                WorkspaceObjectModel.revision == expected_revision,
            )
            .values(revision=WorkspaceObjectModel.revision)
            .returning(WorkspaceObjectModel.id)
        )
        if claimed.scalar_one_or_none() is None:
            await db.rollback()
            current_revision = await db.scalar(
                select(WorkspaceObjectModel.revision).where(WorkspaceObjectModel.id == object_id)
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "WorkspaceObjectRevisionConflict",
                    "message": "Workspace object changed since it was loaded.",
                    "current_revision": current_revision,
                },
            )
        await db.execute(
            sa_delete(WorkspaceEdgeModel).where(
                WorkspaceEdgeModel.project_name == project_name,
                (WorkspaceEdgeModel.source_object_id == object_id) | (WorkspaceEdgeModel.target_object_id == object_id),
            )
        )
        link = await db.get(WorkspaceObjectProjectLinkModel, (object_id, project_name))
        if link is not None:
            await db.delete(link)
        await db.commit()
        return
    if item.created_by != "user" or item.object_type not in {"manual_note", "file_reference", "context_bridge", "context_set", "conversation_branch"}:
        raise HTTPException(status_code=409, detail="Only user-authored workspace objects can be deleted.")
    deleted = await db.execute(
        sa_delete(WorkspaceObjectModel).where(
            WorkspaceObjectModel.id == object_id,
            WorkspaceObjectModel.revision == expected_revision,
        )
    )
    if deleted.rowcount != 1:
        await db.rollback()
        current_revision = await db.scalar(
            select(WorkspaceObjectModel.revision).where(WorkspaceObjectModel.id == object_id)
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WorkspaceObjectRevisionConflict",
                "message": "Workspace object changed since it was loaded.",
                "current_revision": current_revision,
            },
        )
    await db.commit()


@router.post("/projects/{project_name}/edges", response_model=WorkspaceEdgeResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_edge(
    project_name: str,
    body: WorkspaceEdgeCreate,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceEdgeResponse:
    await _lock_project_graph(db, project_name)
    if body.source_object_id == body.target_object_id:
        raise HTTPException(status_code=422, detail="An object cannot be related to itself.")
    objects = await _project_objects_by_ids(db, project_name, [body.source_object_id, body.target_object_id])
    if len(objects) != 2:
        raise HTTPException(status_code=404, detail="Both edge endpoints must exist in this project.")

    if body.edge_family == "context":
        if await _would_create_context_cycle(db, project_name, [body.source_object_id], body.target_object_id):
            raise HTTPException(status_code=409, detail="Context-flow edges must form a DAG.")

    edge = WorkspaceEdgeModel(
        project_name=project_name,
        source_object_id=body.source_object_id,
        target_object_id=body.target_object_id,
        relation_type=body.relation_type,
        edge_family=body.edge_family,
        created_by="user",
        metadata_json=body.metadata_json,
    )
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return _edge_response(edge)


@router.delete("/projects/{project_name}/edges", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_edges(
    project_name: str,
    body: WorkspaceEdgeBatchDelete,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Atomically delete selected user-authored edges after validating every target."""
    edge_ids = list(dict.fromkeys(body.edge_ids))
    await _lock_project_graph(db, project_name)
    result = await db.execute(
        select(WorkspaceEdgeModel)
        .where(
            WorkspaceEdgeModel.project_name == project_name,
            WorkspaceEdgeModel.id.in_(edge_ids),
        )
        .with_for_update()
    )
    edges = list(result.scalars())
    if len(edges) != len(edge_ids):
        raise HTTPException(status_code=404, detail="One or more workspace edges were not found in this project.")
    if any(edge.created_by != "user" for edge in edges):
        raise HTTPException(status_code=409, detail="System-created workspace edges cannot be deleted.")
    await db.execute(
        sa_delete(WorkspaceEdgeModel).where(
            WorkspaceEdgeModel.project_name == project_name,
            WorkspaceEdgeModel.id.in_(edge_ids),
        )
    )
    await db.commit()


@router.post(
    "/projects/{project_name}/edges/batch-restore",
    response_model=list[WorkspaceEdgeResponse],
    status_code=status.HTTP_201_CREATED,
)
async def restore_workspace_edges(
    project_name: str,
    body: WorkspaceEdgeBatchRestore,
    db: AsyncSession = Depends(get_db),
) -> list[WorkspaceEdgeResponse]:
    """Restore a bounded set of user edges with stable IDs after validating the whole batch."""
    edges = body.edges
    edge_ids = [edge.id for edge in edges]
    if len(set(edge_ids)) != len(edge_ids):
        raise HTTPException(status_code=422, detail="Restored workspace edge IDs must be unique.")
    if any(edge.source_object_id == edge.target_object_id for edge in edges):
        raise HTTPException(status_code=422, detail="An object cannot be related to itself.")

    await _lock_project_graph(db, project_name)
    existing_ids = await db.execute(
        select(WorkspaceEdgeModel.id).where(WorkspaceEdgeModel.id.in_(edge_ids))
    )
    if existing_ids.scalars().first() is not None:
        raise HTTPException(status_code=409, detail="One or more workspace edge IDs are already in use.")

    endpoint_ids = [endpoint_id for edge in edges for endpoint_id in (edge.source_object_id, edge.target_object_id)]
    objects = await _project_objects_by_ids(db, project_name, endpoint_ids)
    if len(objects) != len(set(endpoint_ids)):
        raise HTTPException(status_code=404, detail="Both edge endpoints must exist in this project.")

    context_edges = await db.execute(
        select(WorkspaceEdgeModel.source_object_id, WorkspaceEdgeModel.target_object_id).where(
            WorkspaceEdgeModel.project_name == project_name,
            WorkspaceEdgeModel.edge_family == "context",
        )
    )
    adjacency: dict[str, set[str]] = {}
    for source_id, target_id in context_edges:
        adjacency.setdefault(source_id, set()).add(target_id)

    restored: list[WorkspaceEdgeModel] = []
    for item in edges:
        if item.edge_family == "context":
            pending = [item.target_object_id]
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == item.source_object_id:
                    raise HTTPException(status_code=409, detail="Context-flow edges must form a DAG.")
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(adjacency.get(current, ()))
            adjacency.setdefault(item.source_object_id, set()).add(item.target_object_id)
        restored.append(WorkspaceEdgeModel(
            id=item.id,
            project_name=project_name,
            source_object_id=item.source_object_id,
            target_object_id=item.target_object_id,
            relation_type=item.relation_type,
            edge_family=item.edge_family,
            created_by="user",
            metadata_json=item.metadata_json,
        ))

    db.add_all(restored)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Workspace edges could not be restored.") from exc
    for edge in restored:
        await db.refresh(edge)
    return [_edge_response(edge) for edge in restored]


@router.delete("/projects/{project_name}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_edge(project_name: str, edge_id: str, db: AsyncSession = Depends(get_db)) -> None:
    await _lock_project_graph(db, project_name)
    result = await db.execute(
        select(WorkspaceEdgeModel)
        .where(
            WorkspaceEdgeModel.id == edge_id,
            WorkspaceEdgeModel.project_name == project_name,
        )
        .with_for_update()
    )
    edge = result.scalar_one_or_none()
    if edge is None:
        raise HTTPException(status_code=404, detail="Workspace edge not found.")
    if edge.created_by != "user":
        raise HTTPException(status_code=409, detail="System-created workspace edges cannot be deleted.")
    await db.delete(edge)
    await db.commit()


@router.get("/projects/{project_name}/layout", response_model=WorkspaceLayoutResponse)
async def get_workspace_layout(project_name: str, db: AsyncSession = Depends(get_db)) -> WorkspaceLayoutResponse:
    layout = await db.get(WorkspaceLayoutModel, project_name)
    return WorkspaceLayoutResponse(
        project_name=project_name,
        layout=layout.layout_json if layout else {},
        revision=layout.revision if layout else 0,
        updated_at=layout.updated_at if layout else None,
    )


@router.put("/projects/{project_name}/layout", response_model=WorkspaceLayoutResponse)
async def put_workspace_layout(
    project_name: str,
    body: WorkspaceLayoutWrite,
    db: AsyncSession = Depends(get_db),
) -> WorkspaceLayoutResponse:
    await _lock_project_graph(db, project_name)
    layout = await db.get(WorkspaceLayoutModel, project_name, with_for_update=True)
    revision = layout.revision if layout else 0
    if revision != body.expected_revision:
        raise HTTPException(status_code=409, detail={"message": "Board layout changed since it was loaded.", "current_revision": revision})
    merged_layout = dict(layout.layout_json or {}) if layout is not None else {}
    for key, value in body.layout.items():
        if key in {"positions", "densities"} and isinstance(value, dict):
            previous = merged_layout.get(key)
            merged_layout[key] = {**(previous if isinstance(previous, dict) else {}), **value}
        else:
            merged_layout[key] = value
    try:
        validated_layout = WorkspaceLayoutWrite(layout=merged_layout, expected_revision=body.expected_revision).layout
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if layout is None:
        layout = WorkspaceLayoutModel(project_name=project_name, layout_json=validated_layout, revision=1)
        db.add(layout)
    else:
        layout.layout_json = validated_layout
        layout.revision += 1
        layout.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(layout)
    return WorkspaceLayoutResponse(
        project_name=layout.project_name,
        layout=layout.layout_json,
        revision=layout.revision,
        updated_at=layout.updated_at,
    )
