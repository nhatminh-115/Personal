"""Project-scoped durable workspace objects and graph relationships."""

from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    WorkspaceEdgeCreate,
    WorkspaceEdgeResponse,
    WorkspaceExecutionEventResponse,
    WorkspaceExecutionTraceResponse,
    WorkspaceGraphResponse,
    WorkspaceLayoutResponse,
    WorkspaceLayoutWrite,
    WorkspaceObjectCreate,
    WorkspaceObjectResponse,
    WorkspaceObjectUpdate,
    WorkspaceSessionResponse,
)
from app.api.dependencies import get_memory_service
from app.db.models import (
    RunEventModel,
    RunModel,
    SessionModel,
    WorkspaceEdgeModel,
    WorkspaceLayoutModel,
    WorkspaceObjectModel,
)
from app.db.session import get_db
from app.memory.base import MemoryService

router = APIRouter(prefix="/v1/workspace", tags=["Workspace"])

EXECUTION_GRAPH_EVENT_TYPES = {
    "model_selected", "delegation_started", "delegation_completed", "tool_requested", "tool_executed",
    "approval_requested", "approval_granted", "approval_rejected", "response_generated",
    "run_completed", "run_failed", "run_cancelled",
}


def _safe_execution_event(event: RunEventModel) -> WorkspaceExecutionEventResponse:
    """Project only operational identifiers/status; never expose prompts, arguments, or results."""
    payload = event.payload or {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    tool_name = payload.get("tool") or payload.get("tool_name")
    step = payload.get("step")
    return WorkspaceExecutionEventResponse(
        id=event.id,
        event_type=event.event_type,
        created_at=event.created_at,
        agent_role=payload.get("agent_role") if isinstance(payload.get("agent_role"), str) else None,
        specialist=payload.get("specialist") if isinstance(payload.get("specialist"), str) else None,
        provider=payload.get("provider") if isinstance(payload.get("provider"), str) else None,
        model=payload.get("model") if isinstance(payload.get("model"), str) else None,
        tool_name=tool_name if isinstance(tool_name, str) else None,
        tool_call_id=payload.get("tool_call_id") if isinstance(payload.get("tool_call_id"), str) else None,
        child_run_id=payload.get("child_run_id") if isinstance(payload.get("child_run_id"), str) else None,
        status=(payload.get("status") if isinstance(payload.get("status"), str) else None)
        or ("completed" if result.get("success") is True else "failed" if result.get("success") is False else None),
        success=result.get("success") if isinstance(result.get("success"), bool) else None,
        error_category=result.get("error_category") if isinstance(result.get("error_category"), str) else None,
        risk_level=payload.get("risk_level") if isinstance(payload.get("risk_level"), str) else None,
        step=step if isinstance(step, int) and not isinstance(step, bool) else None,
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
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


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


def _would_create_context_cycle(edges: list[WorkspaceEdgeModel], source_id: str, target_id: str) -> bool:
    """Return true when target already reaches source through context-flow edges."""
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.edge_family == "context":
            adjacency[edge.source_object_id].append(edge.target_object_id)
    queue = deque([target_id])
    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        if current == source_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        queue.extend(adjacency[current])
    return False


async def _project_objects_by_ids(db: AsyncSession, project_name: str, ids: list[str]) -> dict[str, WorkspaceObjectModel]:
    if not ids:
        return {}
    result = await db.execute(
        select(WorkspaceObjectModel).where(
            WorkspaceObjectModel.project_name == project_name,
            WorkspaceObjectModel.id.in_(set(ids)),
        )
    )
    return {item.id: item for item in result.scalars()}


@router.get("/projects/{project_name}/graph", response_model=WorkspaceGraphResponse)
async def get_workspace_graph(project_name: str, db: AsyncSession = Depends(get_db)) -> WorkspaceGraphResponse:
    objects = await _get_project_objects(db, project_name)
    edge_result = await db.execute(
        select(WorkspaceEdgeModel)
        .where(WorkspaceEdgeModel.project_name == project_name)
        .order_by(WorkspaceEdgeModel.created_at, WorkspaceEdgeModel.id)
    )
    layout = await db.get(WorkspaceLayoutModel, project_name)
    session_result = await db.execute(select(SessionModel.id).where(SessionModel.project_name == project_name))
    session_ids = list(session_result.scalars())
    runs: list[RunModel] = []
    if session_ids:
        run_result = await db.execute(
            select(RunModel)
            .where(RunModel.session_id.in_(session_ids))
            .order_by(RunModel.created_at.desc(), RunModel.id.desc())
            .limit(100)
        )
        runs = list(run_result.scalars())

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
            .limit(3_000)
        )
        events_by_run: dict[str, list[WorkspaceExecutionEventResponse]] = {run_id: [] for run_id in run_ids}
        for event in event_result.scalars():
            events_by_run[event.run_id].append(_safe_execution_event(event))
        for run_events in events_by_run.values():
            run_events.reverse()

        run_id_set = set(run_ids)
        project_objects = [item for item in objects if item.metadata_json.get("run_id") in run_id_set]
        turn_objects_by_run: dict[str, dict[str, str]] = {}
        for item in project_objects:
            run_id = item.metadata_json.get("run_id")
            role = item.metadata_json.get("role")
            if isinstance(run_id, str) and role in {"user", "assistant"}:
                turn_objects_by_run.setdefault(run_id, {})[role] = item.id
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
    return WorkspaceGraphResponse(
        project_name=project_name,
        objects=[_object_response(item) for item in objects],
        edges=[_edge_response(edge) for edge in edge_result.scalars()],
        layout=WorkspaceLayoutResponse(
            project_name=project_name,
            layout=layout.layout_json if layout else {},
            revision=layout.revision if layout else 0,
            updated_at=layout.updated_at if layout else None,
        ),
        execution_traces=execution_traces,
    )


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
        existing = await db.execute(
            select(WorkspaceEdgeModel).where(
                WorkspaceEdgeModel.project_name == project_name,
                WorkspaceEdgeModel.edge_family == "context",
            )
        )
        edges = list(existing.scalars())
        if any(_would_create_context_cycle(edges, source_id, item.id) for source_id in source_ids):
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
    if item is None or item.project_name != project_name:
        raise HTTPException(status_code=404, detail="Workspace object not found.")
    if item.created_by != "user" or item.object_type not in {"manual_note", "context_bridge"}:
        raise HTTPException(status_code=409, detail="Only user-authored notes and bridges can be edited.")
    item.title = body.title
    item.content = body.content
    item.metadata_json = body.metadata_json
    item.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(item)
    return _object_response(item)


@router.delete("/projects/{project_name}/objects/{object_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_object(project_name: str, object_id: str, db: AsyncSession = Depends(get_db)) -> None:
    item = await db.get(WorkspaceObjectModel, object_id)
    if item is None or item.project_name != project_name:
        raise HTTPException(status_code=404, detail="Workspace object not found.")
    if item.created_by != "user" or item.object_type not in {"manual_note", "context_bridge", "context_set", "conversation_branch"}:
        raise HTTPException(status_code=409, detail="Only user-authored workspace objects can be deleted.")
    await db.delete(item)
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
        existing = await db.execute(
            select(WorkspaceEdgeModel).where(
                WorkspaceEdgeModel.project_name == project_name,
                WorkspaceEdgeModel.edge_family == "context",
            )
        )
        if _would_create_context_cycle(list(existing.scalars()), body.source_object_id, body.target_object_id):
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


@router.delete("/projects/{project_name}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_edge(project_name: str, edge_id: str, db: AsyncSession = Depends(get_db)) -> None:
    edge = await db.get(WorkspaceEdgeModel, edge_id)
    if edge is None or edge.project_name != project_name:
        raise HTTPException(status_code=404, detail="Workspace edge not found.")
    await db.delete(edge)
    await db.commit()


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
    if layout is None:
        layout = WorkspaceLayoutModel(project_name=project_name, layout_json=body.layout, revision=1)
        db.add(layout)
    else:
        layout.layout_json = body.layout
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
