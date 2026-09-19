"""Runs and trace auditing endpoint: GET /v1/runs/{id}."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trace_service
from sqlalchemy import select
from app.api.schemas import ResearchInspectorResponse, RunDetailResponse, RunEventResponse
from app.db.models import DelegationModel
from app.db.session import get_db
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run_details(
    run_id: str,
    trace_service: TraceService = Depends(get_trace_service),
) -> RunDetailResponse:
    """Inspect execution details and chronological event trace of a run."""
    run = await trace_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    events = await trace_service.get_run_events(run_id)

    return RunDetailResponse(
        id=run.id,
        session_id=run.session_id,
        status=run.status,
        user_message=run.user_message,
        final_response=run.final_response,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
        events=[
            RunEventResponse(
                id=e.id,
                event_type=e.event_type,
                payload=e.payload,
                created_at=e.created_at,
            )
            for e in events
        ],
    )


@router.get("/{run_id}/research", response_model=ResearchInspectorResponse)
async def get_run_research(
    run_id: str,
    db: AsyncSession = Depends(get_db),
) -> ResearchInspectorResponse:
    """Retrieve checkpointed ResearchState for a parent or child research specialist run."""
    # 1. Look up delegation record
    del_stmt = select(DelegationModel).where(
        (DelegationModel.parent_run_id == run_id) | (DelegationModel.child_run_id == run_id)
    ).where(DelegationModel.specialist_name == "research")
    del_res = await db.execute(del_stmt)
    delegation = del_res.scalar_one_or_none()

    target_child_run_id = delegation.child_run_id if delegation else run_id

    # 2. Inspect checkpointed state
    try:
        graph = await get_compiled_graph()
        snapshot = await graph.aget_state({"configurable": {"thread_id": target_child_run_id}})
        r_dict = (
            snapshot.values.get("research_state")
            if snapshot and hasattr(snapshot, "values")
            else None
        )
    except Exception:
        r_dict = None

    if not r_dict:
        return ResearchInspectorResponse(
            run_id=run_id,
            child_run_id=delegation.child_run_id if delegation else None,
            status="none",
        )

    # Normalize dictionaries
    sources_raw = r_dict.get("sources", {})
    sources_list = list(sources_raw.values()) if isinstance(sources_raw, dict) else (sources_raw or [])

    evidence_raw = r_dict.get("evidence", {})
    evidence_list = list(evidence_raw.values()) if isinstance(evidence_raw, dict) else (evidence_raw or [])

    return ResearchInspectorResponse(
        run_id=run_id,
        child_run_id=delegation.child_run_id if delegation else None,
        goal=r_dict.get("goal"),
        queries=r_dict.get("queries", []),
        sources=sources_list,
        inspected_source_ids=r_dict.get("inspected_source_ids", []),
        evidence=evidence_list,
        claims=r_dict.get("claims", []),
        status=r_dict.get("status", "unknown"),
    )
