"""Runs and trace auditing endpoint: GET /v1/runs/{id}."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trace_service
from app.api.schemas import RunDetailResponse, RunEventResponse
from app.observability.tracer import TraceService

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
