"""Durable user automation definitions backed by the persistent scheduler."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AutomationExecutionResponse, AutomationResponse, AutomationRunResponse, AutomationWrite
from app.db.models import EventRecordModel, EventStatus, JobType, RunModel, RunStatus, ScheduledJobModel, utc_now
from app.db.session import get_db
from app.events.bus import event_bus
from app.events.types import AURAEvent, EventType

router = APIRouter(prefix="/v1/automations", tags=["Automations"])


class AutomationEnabledWrite(BaseModel):
    enabled: bool


def _automation_response(job: ScheduledJobModel) -> AutomationResponse:
    metadata = job.metadata_json or {}
    try:
        interval_seconds = int(float(job.schedule_expression))
    except (TypeError, ValueError):
        interval_seconds = 0
    scope = metadata.get("scope")
    return AutomationResponse(
        id=job.id,
        name=job.name,
        description=metadata.get("description", ""),
        instruction=metadata.get("instruction", ""),
        enabled=job.is_active,
        scope=scope if scope in {"global", "project"} else "global",
        project_name=metadata.get("project_name") if isinstance(metadata.get("project_name"), str) else None,
        interval_seconds=interval_seconds,
        last_run_at=job.last_run_at,
        next_run_at=job.next_run_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _latest_executions(db: AsyncSession, jobs: list[ScheduledJobModel]) -> dict[str, AutomationExecutionResponse]:
    job_ids = [job.id for job in jobs]
    if not job_ids:
        return {}
    latest_event_ids = (
        select(
            EventRecordModel.id.label("event_id"),
            func.row_number().over(
                partition_by=EventRecordModel.correlation_id,
                order_by=(EventRecordModel.occurred_at.desc(), EventRecordModel.id.desc()),
            ).label("position"),
        )
        .where(
            EventRecordModel.correlation_id.in_(job_ids),
            EventRecordModel.event_type.in_({"timer.fired", "cron.tick"}),
        )
        .subquery()
    )
    result = await db.execute(
        select(EventRecordModel)
        .join(latest_event_ids, latest_event_ids.c.event_id == EventRecordModel.id)
        .where(latest_event_ids.c.position == 1)
    )
    latest: dict[str, EventRecordModel] = {}
    for event in result.scalars():
        if event.correlation_id:
            latest[event.correlation_id] = event
    run_id_by_event = {
        event.id: str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))
        for event in latest.values()
    }
    run_ids = list(run_id_by_event.values())
    run_result = await db.execute(select(RunModel).where(RunModel.id.in_(run_ids))) if run_ids else None
    runs = {run.id: run for run in run_result.scalars()} if run_result is not None else {}
    response: dict[str, AutomationExecutionResponse] = {}
    for automation_id, event in latest.items():
        run_id = run_id_by_event[event.id]
        run = runs.get(run_id)
        event_status = {
            EventStatus.PENDING.value: "queued",
            EventStatus.PROCESSING.value: "running",
            EventStatus.PROCESSED.value: "completed",
            EventStatus.FAILED.value: "failed",
            EventStatus.DEAD_LETTER.value: "failed",
        }.get(event.status, event.status)
        response[automation_id] = AutomationExecutionResponse(
            event_id=event.id,
            run_id=run_id,
            queued_at=event.occurred_at,
            status=run.status if run is not None else event_status,
            retry_count=event.retry_count,
        )
    return response


@router.get("", response_model=list[AutomationResponse])
async def list_automations(db: AsyncSession = Depends(get_db)) -> list[AutomationResponse]:
    result = await db.execute(select(ScheduledJobModel).order_by(ScheduledJobModel.created_at.desc(), ScheduledJobModel.id))
    jobs = [job for job in result.scalars() if (job.metadata_json or {}).get("kind") == "automation"]
    latest = await _latest_executions(db, jobs)
    return [_automation_response(job).model_copy(update={"latest_execution": latest.get(job.id)}) for job in jobs]


@router.post("", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(body: AutomationWrite, db: AsyncSession = Depends(get_db)) -> AutomationResponse:
    name = body.name.strip()
    instruction = body.instruction.strip()
    if not name or not instruction:
        raise HTTPException(status_code=422, detail="Automation name and instruction must not be blank.")
    if body.scope == "project" and not (body.project_name or "").strip():
        raise HTTPException(status_code=422, detail="Project-scoped automations require a project.")

    now = utc_now()
    job = ScheduledJobModel(
        name=name,
        job_type=JobType.RECURRING.value,
        schedule_expression=str(body.interval_seconds),
        payload_json={},
        is_active=True,
        next_run_at=now + timedelta(seconds=body.interval_seconds),
        metadata_json={},
    )
    db.add(job)
    await db.flush()
    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-automation-session:{job.id}"))
    job.payload_json = {
        "message": instruction,
        "session_id": session_id,
        "project_name": body.project_name.strip() if body.scope == "project" and body.project_name else None,
        "automation_id": job.id,
    }
    job.metadata_json = {
        "kind": "automation",
        "description": body.description.strip(),
        "instruction": instruction,
        "scope": body.scope,
        "project_name": body.project_name.strip() if body.scope == "project" and body.project_name else None,
    }
    await db.commit()
    await db.refresh(job)
    latest = await _latest_executions(db, [job])
    return _automation_response(job).model_copy(update={"latest_execution": latest.get(job.id)})


@router.put("/{automation_id}", response_model=AutomationResponse)
async def set_automation_enabled(
    automation_id: str,
    body: AutomationEnabledWrite,
    db: AsyncSession = Depends(get_db),
) -> AutomationResponse:
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")
    was_enabled = job.is_active
    job.is_active = body.enabled
    if body.enabled and not was_enabled:
        try:
            interval = max(60, int(float(job.schedule_expression)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=409, detail="Automation interval is invalid.")
        job.next_run_at = utc_now() + timedelta(seconds=interval)
    job.updated_at = utc_now()
    await db.commit()
    await db.refresh(job)
    return _automation_response(job)


@router.post("/{automation_id}/run", response_model=AutomationRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_automation_now(automation_id: str, db: AsyncSession = Depends(get_db)) -> AutomationRunResponse:
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")
    if not job.is_active:
        raise HTTPException(status_code=409, detail="Paused automations cannot be run.")

    now = utc_now()
    claim_token = f"manual-{uuid.uuid4().hex}"
    stale_lock_cutoff = now - timedelta(seconds=60)
    claim = await db.execute(
        update(ScheduledJobModel)
        .where(
            and_(
                ScheduledJobModel.id == automation_id,
                ScheduledJobModel.is_active.is_(True),
                or_(
                    ScheduledJobModel.locked_at.is_(None),
                    ScheduledJobModel.locked_at < stale_lock_cutoff,
                ),
            )
        )
        .values(locked_at=now, locked_by=claim_token)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    if claim.rowcount == 0:
        current = await db.execute(
            select(ScheduledJobModel)
            .where(ScheduledJobModel.id == automation_id)
            .execution_options(populate_existing=True)
        )
        current_job = current.scalar_one_or_none()
        if current_job is None or (current_job.metadata_json or {}).get("kind") != "automation":
            raise HTTPException(status_code=404, detail="Automation not found.")
        if not current_job.is_active:
            raise HTTPException(status_code=409, detail="Paused automations cannot be run.")
        raise HTTPException(status_code=409, detail="The scheduler is already dispatching this automation.")

    try:
        current = await db.execute(
            select(ScheduledJobModel)
            .where(ScheduledJobModel.id == automation_id)
            .execution_options(populate_existing=True)
        )
        job = current.scalar_one()
        latest = (await _latest_executions(db, [job])).get(job.id)
        if latest and latest.status in {
            "queued",
            "running",
            RunStatus.WAITING_FOR_APPROVAL.value,
            RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value,
        }:
            raise HTTPException(
                status_code=409,
                detail="This automation already has a run awaiting execution or completion.",
            )
        event = AURAEvent(
            event_type=EventType.TIMER_FIRED.value,
            source="automation",
            payload={**(job.payload_json or {}), "manual": True},
            correlation_id=job.id,
            idempotency_key=f"automation-manual-{job.id}-{uuid.uuid4()}",
        )
        queued = await event_bus.publish(event, db=db, dispatch_immediate=False)
        return AutomationRunResponse(event_id=queued.id)
    finally:
        await db.execute(
            update(ScheduledJobModel)
            .where(
                ScheduledJobModel.id == automation_id,
                ScheduledJobModel.locked_by == claim_token,
            )
            .values(locked_at=None, locked_by=None)
        )
        await db.commit()

@router.get("/{automation_id}/runs", response_model=list[AutomationExecutionResponse])
async def list_automation_runs(
    automation_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[AutomationExecutionResponse]:
    """Return recent safe status summaries without exposing instructions or run output."""
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")

    result = await db.execute(
        select(EventRecordModel)
        .where(
            EventRecordModel.correlation_id == automation_id,
            EventRecordModel.event_type.in_({"timer.fired", "cron.tick"}),
        )
        .order_by(EventRecordModel.occurred_at.desc(), EventRecordModel.id.desc())
        .limit(limit)
    )
    events = list(result.scalars())
    run_ids = [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}"))
        for event in events
    ]
    run_result = await db.execute(select(RunModel).where(RunModel.id.in_(run_ids))) if run_ids else None
    runs = {run.id: run for run in run_result.scalars()} if run_result is not None else {}
    event_status = {
        EventStatus.PENDING.value: "queued",
        EventStatus.PROCESSING.value: "running",
        EventStatus.PROCESSED.value: "completed",
        EventStatus.FAILED.value: "failed",
        EventStatus.DEAD_LETTER.value: "failed",
    }
    return [
        AutomationExecutionResponse(
            event_id=event.id,
            run_id=run_id,
            queued_at=event.occurred_at,
            status=runs[run_id].status if run_id in runs else event_status.get(event.status, event.status),
            retry_count=event.retry_count,
        )
        for event, run_id in zip(events, run_ids)
    ]

