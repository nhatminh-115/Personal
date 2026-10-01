"""Project-scoped durable workspace objects and graph relationships."""

from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    WorkspaceEdgeCreate,
    WorkspaceEdgeResponse,
    WorkspaceGraphResponse,
    WorkspaceLayoutResponse,
    WorkspaceLayoutWrite,
    WorkspaceObjectCreate,
    WorkspaceObjectResponse,
    WorkspaceObjectUpdate,
    WorkspaceSessionResponse,
)
from app.api.dependencies import get_memory_service
from app.db.models import WorkspaceEdgeModel, WorkspaceLayoutModel, WorkspaceObjectModel
from app.db.session import get_db
from app.memory.base import MemoryService

router = APIRouter(prefix="/v1/workspace", tags=["Workspace"])


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

    item = WorkspaceObjectModel(
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
    if item.created_by != "user" or item.object_type not in {"manual_note", "context_bridge"}:
        raise HTTPException(status_code=409, detail="Only user-authored notes and bridges can be deleted.")
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
