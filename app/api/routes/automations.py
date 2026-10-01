"""Durable, local-only scheduled root-agent automations."""

from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AutomationCreate, AutomationResponse, AutomationUpdate
from app.db.models import RunModel, ScheduledJobModel, utc_now
from app.db.session import get_db
from app.events.bus import event_bus
from app.events.types import AURAEvent, EventType

router = APIRouter(prefix="/v1/automations", tags=["Automations"])


def _interval_seconds(job: ScheduledJobModel) -> int:
    try:
        return max(0, int(float(job.schedule_expression)))
    except (TypeError, ValueError):
        return 0


async def _response(job: ScheduledJobModel, db: AsyncSession) -> AutomationResponse:
    payload = job.payload_json or {}
    metadata = job.metadata_json or {}
    last_run_id = None
    last_run_status = None
    if job.last_run_at:
        run = await db.scalar(
            select(RunModel)
            .where(RunModel.session_id == job.id)
            .order_by(RunModel.created_at.desc(), RunModel.id.desc())
            .limit(1)
        )
        if run:
            last_run_id = run.id
            last_run_status = run.status
    return AutomationResponse(
        id=job.id,
        name=job.name,
        description=str(metadata.get("description") or ""),
        message=str(payload.get("message") or ""),
        project_name=payload.get("project_name") if isinstance(payload.get("project_name"), str) else None,
        is_active=job.is_active,
        interval_seconds=_interval_seconds(job),
        next_run_at=job.next_run_at,
        last_run_at=job.last_run_at,
        last_run_status=last_run_status,
        last_run_id=last_run_id,
    )


async def _get_automation(db: AsyncSession, automation_id: str) -> ScheduledJobModel:
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation" or (job.metadata_json or {}).get("deleted_at"):
        raise HTTPException(status_code=404, detail="Automation not found.")
    return job


@router.get("", response_model=list[AutomationResponse])
async def list_automations(db: AsyncSession = Depends(get_db)) -> list[AutomationResponse]:
    result = await db.execute(
        select(ScheduledJobModel)
        .order_by(ScheduledJobModel.created_at.desc(), ScheduledJobModel.id)
        .limit(500)
    )
    jobs = [
        job for job in result.scalars()
        if (job.metadata_json or {}).get("kind") == "automation"
        and not (job.metadata_json or {}).get("deleted_at")
    ]
    return [await _response(job, db) for job in jobs]


@router.post("", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(body: AutomationCreate, db: AsyncSession = Depends(get_db)) -> AutomationResponse:
    name = body.name.strip()
    message = body.message.strip()
    if not name or not message:
        raise HTTPException(status_code=422, detail="Name and prompt must contain non-whitespace text.")
    automation_id = str(uuid4())
    interval_seconds = body.interval_seconds
    job = ScheduledJobModel(
        id=automation_id,
        name=name,
        job_type="recurring",
        schedule_expression=str(interval_seconds),
        payload_json={
            "automation": {"version": 1},
            "automation_id": automation_id,
            "session_id": automation_id,
            "message": message,
            "project_name": body.project_name.strip() or None if body.project_name else None,
            "metadata": {"automation_id": automation_id, "force_local_only": True},
        },
        is_active=True,
        next_run_at=utc_now() + timedelta(seconds=interval_seconds),
        metadata_json={"kind": "automation", "description": body.description.strip()},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return await _response(job, db)


@router.put("/{automation_id}", response_model=AutomationResponse)
async def update_automation(
    automation_id: str,
    body: AutomationUpdate,
    db: AsyncSession = Depends(get_db),
) -> AutomationResponse:
    job = await _get_automation(db, automation_id)
    if body.is_active and not job.is_active:
        next_run_at = job.next_run_at
        if next_run_at.tzinfo is None:
            next_run_at = next_run_at.replace(tzinfo=timezone.utc)
        now = utc_now()
        if next_run_at <= now:
            job.next_run_at = now + timedelta(seconds=max(3600, _interval_seconds(job)))
    job.is_active = body.is_active
    job.updated_at = utc_now()
    await db.commit()
    await db.refresh(job)
    return await _response(job, db)


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(automation_id: str, db: AsyncSession = Depends(get_db)) -> None:
    job = await _get_automation(db, automation_id)
    job.is_active = False
    job.metadata_json = {**(job.metadata_json or {}), "deleted_at": utc_now().isoformat()}
    job.updated_at = utc_now()
    await db.commit()


@router.post("/{automation_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_automation_now(automation_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    job = await _get_automation(db, automation_id)
    if not job.is_active:
        raise HTTPException(status_code=409, detail="Paused automations cannot be run.")
    event = AURAEvent(
        event_type=EventType.TASK_RESUMED.value,
        source="automation",
        payload={**(job.payload_json or {}), "trigger": "manual"},
        correlation_id=job.id,
        idempotency_key=f"automation-manual-{job.id}-{uuid4()}",
    )
    await event_bus.publish(event, db=db, dispatch_immediate=False)
    job.last_run_at = utc_now()
    job.updated_at = utc_now()
    await db.commit()
    return {"automation_id": job.id, "event_id": event.id, "status": "queued"}
