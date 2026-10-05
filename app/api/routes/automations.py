"""Durable user automation definitions backed by the persistent scheduler."""

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import AutomationDuplicateWrite, AutomationEditWrite, AutomationExecutionResponse, AutomationResponse, AutomationRevisionWrite, AutomationRunResponse, AutomationSchedule, AutomationWrite
from app.api.pagination import (
    MAX_COLLECTION_PAGE_SIZE,
    decode_timestamp_id_cursor,
    set_next_cursor_header,
)
from app.db.models import EventRecordModel, EventStatus, JobType, RunModel, RunStatus, ScheduledJobModel, utc_now
from app.db.session import get_db
from app.events.bus import event_bus
from app.events.automation_schedule import next_automation_run
from app.events.scheduler import persistent_scheduler
from app.events.types import AURAEvent, EventType

router = APIRouter(prefix="/v1/automations", tags=["Automations"])
WEBHOOK_EVENT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _automation_trigger_type(event_type: str, source: str | None = None) -> str:
    if source == "automation_retry":
        return "retry"
    return {
        EventType.CRON_TICK.value: "schedule",
        EventType.WEBHOOK_RECEIVED.value: "webhook",
    }.get(event_type, "manual")


async def _claim_automation_dispatch(db: AsyncSession, automation_id: str, claim_prefix: str) -> str | None:
    """Acquire a DB-atomic short lease shared by manual, webhook, retry, and scheduler dispatches."""
    now = utc_now()
    claim_token = f"{claim_prefix}-{uuid.uuid4().hex}"
    result = await db.execute(
        update(ScheduledJobModel)
        .where(
            and_(
                ScheduledJobModel.id == automation_id,
                ScheduledJobModel.is_active.is_(True),
                or_(
                    ScheduledJobModel.locked_at.is_(None),
                    ScheduledJobModel.locked_at < now - timedelta(seconds=60),
                ),
            )
        )
        .values(locked_at=now, locked_by=claim_token)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return claim_token if result.rowcount == 1 else None


async def _release_automation_dispatch(db: AsyncSession, automation_id: str, claim_token: str) -> None:
    await db.execute(
        update(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id, ScheduledJobModel.locked_by == claim_token)
        .values(locked_at=None, locked_by=None)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


class AutomationEnabledWrite(BaseModel):
    enabled: bool
    expected_revision: int


class WebhookRunResponse(BaseModel):
    event_id: str
    status: str = "queued"


def _automation_response(job: ScheduledJobModel) -> AutomationResponse:
    metadata = job.metadata_json or {}
    try:
        interval_seconds = int(float(job.schedule_expression))
    except (TypeError, ValueError):
        interval_seconds = 0
    try:
        schedule = AutomationSchedule.model_validate(metadata.get("schedule", {}))
    except (TypeError, ValueError):
        # Older scheduled jobs have only interval_seconds in schedule_expression.
        schedule = AutomationSchedule()
    scope = metadata.get("scope")
    return AutomationResponse(
        id=job.id,
        revision=job.revision,
        name=job.name,
        description=metadata.get("description", ""),
        instruction=metadata.get("instruction", ""),
        enabled=job.is_active,
        archived=metadata.get("archived") is True,
        scope=scope if scope in {"global", "project"} else "global",
        project_name=metadata.get("project_name") if isinstance(metadata.get("project_name"), str) else None,
        interval_seconds=interval_seconds,
        schedule=schedule,
        webhook_enabled=bool(metadata.get("webhook_secret_hash")),
        webhook_path=f"/v1/automations/{job.id}/webhook/events" if metadata.get("webhook_secret_hash") else None,
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
            EventRecordModel.event_type.in_({"timer.fired", "cron.tick", EventType.WEBHOOK_RECEIVED.value}),
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
            EventStatus.CANCELLED.value: "cancelled",
            EventStatus.FAILED.value: "failed",
            EventStatus.DEAD_LETTER.value: "dead_letter",
        }.get(event.status, event.status)
        execution_status = (
            "dead_letter"
            if event.status == EventStatus.DEAD_LETTER.value
            else run.status if run is not None else event_status
        )
        response[automation_id] = AutomationExecutionResponse(
            event_id=event.id,
            run_id=run_id,
            queued_at=event.occurred_at,
            status=execution_status,
            retry_count=event.retry_count,
            trigger_type=_automation_trigger_type(event.event_type, event.source),
            retry_of_event_id=(
                event.payload_json.get("retry_of_event_id")
                if isinstance(event.payload_json, dict) and isinstance(event.payload_json.get("retry_of_event_id"), str)
                else None
            ),
        )
    return response


@router.get("", response_model=list[AutomationResponse])
async def list_automations(
    response: Response,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int = Query(default=100, ge=1, le=MAX_COLLECTION_PAGE_SIZE),
    include_archived: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> list[AutomationResponse]:
    query = select(ScheduledJobModel).where(
        ScheduledJobModel.metadata_json["kind"].as_string() == "automation"
    )
    if not include_archived:
        archived = ScheduledJobModel.metadata_json["archived"].as_boolean()
        query = query.where(or_(archived.is_(None), archived.is_(False)))
    if cursor is not None:
        cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
        query = query.where(or_(
            ScheduledJobModel.created_at < cursor_created_at,
            and_(ScheduledJobModel.created_at == cursor_created_at, ScheduledJobModel.id > cursor_id),
        ))
    result = await db.execute(
        query.order_by(ScheduledJobModel.created_at.desc(), ScheduledJobModel.id).limit(page_size + 1)
    )
    jobs = set_next_cursor_header(
        response, list(result.scalars()), page_size,
        timestamp_for=lambda item: item.created_at,
        id_for=lambda item: item.id,
    )
    latest = await _latest_executions(db, jobs)
    return [_automation_response(job).model_copy(update={"latest_execution": latest.get(job.id)}) for job in jobs]


@router.get("/status", response_model=list[AutomationResponse])
async def get_automation_statuses(
    automation_ids: list[str] = Query(min_length=1, max_length=MAX_COLLECTION_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
) -> list[AutomationResponse]:
    """Refresh a bounded set of automation records without scanning the collection."""
    result = await db.execute(
        select(ScheduledJobModel)
        .where(
            ScheduledJobModel.id.in_(set(automation_ids)),
            ScheduledJobModel.metadata_json["kind"].as_string() == "automation",
        )
        .order_by(ScheduledJobModel.created_at.desc(), ScheduledJobModel.id)
    )
    jobs = list(result.scalars())
    latest = await _latest_executions(db, jobs)
    return [_automation_response(job).model_copy(update={"latest_execution": latest.get(job.id)}) for job in jobs]


@router.get("/summary", response_model=dict[str, int])
async def get_automation_summary(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    automation_filter = ScheduledJobModel.metadata_json["kind"].as_string() == "automation"
    archived_filter = ScheduledJobModel.metadata_json["archived"].as_boolean()
    visible_filter = or_(archived_filter.is_(None), archived_filter.is_(False))
    total = await db.scalar(select(func.count()).select_from(ScheduledJobModel).where(automation_filter, visible_filter))
    enabled = await db.scalar(
        select(func.count()).select_from(ScheduledJobModel).where(automation_filter, visible_filter, ScheduledJobModel.is_active.is_(True))
    )
    return {"total": int(total or 0), "enabled": int(enabled or 0)}


@router.post("", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(body: AutomationWrite, db: AsyncSession = Depends(get_db)) -> AutomationResponse:
    name = body.name.strip()
    instruction = body.instruction.strip()
    if not name or not instruction:
        raise HTTPException(status_code=422, detail="Automation name and instruction must not be blank.")
    if body.scope == "project" and not (body.project_name or "").strip():
        raise HTTPException(status_code=422, detail="Project-scoped automations require a project.")

    now = utc_now()
    schedule = body.schedule
    webhook_secret = secrets.token_urlsafe(32) if body.webhook_enabled else None
    job = ScheduledJobModel(
        name=name,
        job_type=JobType.RECURRING.value,
        schedule_expression=str(body.interval_seconds),
        payload_json={},
        is_active=True,
        next_run_at=next_automation_run(schedule, now, body.interval_seconds),
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
        "schedule": schedule.model_dump(),
    }
    if webhook_secret:
        job.metadata_json["webhook_secret_hash"] = hashlib.sha256(webhook_secret.encode("utf-8")).hexdigest()
    await db.commit()
    await db.refresh(job)
    latest = await _latest_executions(db, [job])
    return _automation_response(job).model_copy(update={"latest_execution": latest.get(job.id), "webhook_secret": webhook_secret})


@router.put("/{automation_id}", response_model=AutomationResponse)
async def set_automation_enabled(
    automation_id: str,
    body: AutomationEnabledWrite,
    db: AsyncSession = Depends(get_db),
) -> AutomationResponse:
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation" or (job.metadata_json or {}).get("archived") is True:
        raise HTTPException(status_code=404, detail="Automation not found.")
    if job.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail={"code": "AutomationRevisionConflict", "message": "Automation changed since it was loaded.", "current_revision": job.revision})
    was_enabled = job.is_active
    next_run_at = job.next_run_at
    if body.enabled and not was_enabled:
        try:
            interval = max(60, int(float(job.schedule_expression)))
        except (TypeError, ValueError):
            raise HTTPException(status_code=409, detail="Automation interval is invalid.")
        schedule = AutomationSchedule.model_validate((job.metadata_json or {}).get("schedule", {}))
        next_run_at = next_automation_run(schedule, utc_now(), interval)
    updated_at = utc_now()
    result = await db.execute(
        update(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id, ScheduledJobModel.revision == body.expected_revision)
        .values(
            is_active=body.enabled,
            next_run_at=next_run_at,
            revision=ScheduledJobModel.revision + 1,
            updated_at=updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        current_revision = await db.scalar(select(ScheduledJobModel.revision).where(ScheduledJobModel.id == automation_id))
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Automation not found.")
        raise HTTPException(status_code=409, detail={"message": "Automation changed since it was loaded.", "current_revision": current_revision})
    await db.commit()
    await db.refresh(job)
    return _automation_response(job)


@router.patch("/{automation_id}", response_model=AutomationResponse)
async def update_automation(
    automation_id: str,
    body: AutomationEditWrite,
    db: AsyncSession = Depends(get_db),
) -> AutomationResponse:
    result = await db.execute(
        select(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = result.scalar_one_or_none()
    if job is None or (job.metadata_json or {}).get("kind") != "automation" or (job.metadata_json or {}).get("archived") is True:
        raise HTTPException(status_code=404, detail="Automation not found.")
    if job.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail={"code": "AutomationRevisionConflict", "message": "Automation changed since it was loaded.", "current_revision": job.revision})
    if not body.name.strip() or not body.instruction.strip():
        raise HTTPException(status_code=422, detail="Automation name and instruction must not be blank.")

    metadata = dict(job.metadata_json or {})
    payload = dict(job.payload_json or {})
    try:
        previous_interval = int(float(job.schedule_expression))
    except (TypeError, ValueError):
        previous_interval = 0
    previous_schedule_data = metadata.get("schedule", {})
    previous_schedule = AutomationSchedule.model_validate(previous_schedule_data)
    schedule = body.schedule or previous_schedule
    next_run_at = job.next_run_at
    if previous_interval != body.interval_seconds or schedule != previous_schedule:
        next_run_at = next_automation_run(schedule, utc_now(), body.interval_seconds)
    metadata["description"] = body.description.strip()
    metadata["instruction"] = body.instruction.strip()
    metadata["schedule"] = schedule.model_dump()
    webhook_secret = None
    if body.webhook_enabled is True and not metadata.get("webhook_secret_hash"):
        webhook_secret = secrets.token_urlsafe(32)
        metadata["webhook_secret_hash"] = hashlib.sha256(webhook_secret.encode("utf-8")).hexdigest()
    elif body.webhook_enabled is False:
        metadata.pop("webhook_secret_hash", None)
    payload["message"] = body.instruction.strip()
    updated_at = utc_now()
    result = await db.execute(
        update(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id, ScheduledJobModel.revision == body.expected_revision)
        .values(
            name=body.name.strip(),
            schedule_expression=str(body.interval_seconds),
            next_run_at=next_run_at,
            metadata_json=metadata,
            payload_json=payload,
            revision=ScheduledJobModel.revision + 1,
            updated_at=updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        current_revision = await db.scalar(select(ScheduledJobModel.revision).where(ScheduledJobModel.id == automation_id))
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Automation not found.")
        raise HTTPException(status_code=409, detail={"code": "AutomationRevisionConflict", "message": "Automation changed since it was loaded.", "current_revision": current_revision})
    await db.commit()
    await db.refresh(job)
    latest = await _latest_executions(db, [job])
    return _automation_response(job).model_copy(update={"latest_execution": latest.get(job.id), "webhook_secret": webhook_secret})


@router.post("/{automation_id}/webhook/events", response_model=WebhookRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_automation_webhook(
    automation_id: str,
    authorization: str | None = Header(default=None),
    event_id: str | None = Header(default=None, alias="X-Aura-Event-Id"),
    db: AsyncSession = Depends(get_db),
) -> WebhookRunResponse:
    """Queue an authenticated webhook signal without retaining its caller-supplied body."""
    result = await db.execute(
        select(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = result.scalar_one_or_none()
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")
    metadata = job.metadata_json if isinstance(job.metadata_json, dict) else {}
    secret_hash = metadata.get("webhook_secret_hash")
    if not isinstance(secret_hash, str) or not secret_hash:
        raise HTTPException(status_code=404, detail="Webhook trigger is not configured.")
    token = authorization[7:].strip() if isinstance(authorization, str) and authorization.lower().startswith("bearer ") else ""
    supplied_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not token or not hmac.compare_digest(supplied_hash, secret_hash):
        raise HTTPException(status_code=401, detail="Webhook authentication failed.", headers={"WWW-Authenticate": "Bearer"})
    if metadata.get("archived") is True:
        raise HTTPException(status_code=404, detail="Automation not found.")
    if not job.is_active:
        raise HTTPException(status_code=409, detail="Paused automations cannot be triggered.")
    if not isinstance(event_id, str) or not WEBHOOK_EVENT_ID.fullmatch(event_id):
        raise HTTPException(status_code=422, detail="X-Aura-Event-Id must contain 1–128 letters, digits, dots, underscores, colons, or hyphens.")
    idempotency_key = f"automation-webhook-{job.id}-{event_id}"
    duplicate = await db.scalar(select(EventRecordModel).where(EventRecordModel.idempotency_key == idempotency_key))
    if duplicate is not None:
        return WebhookRunResponse(event_id=duplicate.id)
    claim_token = await _claim_automation_dispatch(db, job.id, "webhook")
    if claim_token is None:
        duplicate = await db.scalar(select(EventRecordModel).where(EventRecordModel.idempotency_key == idempotency_key))
        if duplicate is not None:
            return WebhookRunResponse(event_id=duplicate.id)
        raise HTTPException(status_code=409, detail="This automation is already dispatching another run.")
    try:
        current = await db.execute(
            select(ScheduledJobModel)
            .where(ScheduledJobModel.id == automation_id)
            .execution_options(populate_existing=True)
        )
        job = current.scalar_one_or_none()
        metadata = job.metadata_json if job is not None and isinstance(job.metadata_json, dict) else {}
        current_secret_hash = metadata.get("webhook_secret_hash")
        if job is None or metadata.get("kind") != "automation" or metadata.get("archived") is True:
            raise HTTPException(status_code=404, detail="Automation not found.")
        if not isinstance(current_secret_hash, str) or not hmac.compare_digest(supplied_hash, current_secret_hash):
            raise HTTPException(status_code=404, detail="Webhook trigger is not configured.")
        if not job.is_active:
            raise HTTPException(status_code=409, detail="Paused automations cannot be triggered.")
        if await persistent_scheduler.has_active_automation_execution(db, job):
            raise HTTPException(status_code=409, detail="This automation already has a run awaiting execution or completion.")

        payload = job.payload_json if isinstance(job.payload_json, dict) else {}
        event = AURAEvent(
            event_type=EventType.WEBHOOK_RECEIVED.value,
            source="authenticated_webhook",
            payload={
                "message": payload.get("message"),
                "session_id": payload.get("session_id"),
                "project_name": payload.get("project_name"),
                "automation_id": job.id,
            },
            correlation_id=job.id,
            idempotency_key=idempotency_key,
        )
        published = await event_bus.publish(event, db=db, dispatch_immediate=False)
        return WebhookRunResponse(event_id=published.id)
    finally:
        await _release_automation_dispatch(db, automation_id, claim_token)


async def _set_archived_state(automation_id: str, archived: bool, expected_revision: int, db: AsyncSession) -> AutomationResponse:
    result = await db.execute(
        select(ScheduledJobModel).where(ScheduledJobModel.id == automation_id)
        .with_for_update().execution_options(populate_existing=True)
    )
    job = result.scalar_one_or_none()
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")
    if job.revision != expected_revision:
        raise HTTPException(status_code=409, detail={"code": "AutomationRevisionConflict", "message": "Automation changed since it was loaded.", "current_revision": job.revision})
    metadata = dict(job.metadata_json or {})
    was_archived = metadata.get("archived") is True
    if not archived and not was_archived:
        latest = await _latest_executions(db, [job])
        return _automation_response(job).model_copy(update={"latest_execution": latest.get(job.id)})
    if archived:
        metadata["archived"] = True
    else:
        metadata.pop("archived", None)
    updated_at = utc_now()
    result = await db.execute(
        update(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id, ScheduledJobModel.revision == expected_revision)
        .values(
            metadata_json=metadata,
            # Restored automations stay paused until the user explicitly resumes them.
            is_active=False,
            revision=ScheduledJobModel.revision + 1,
            updated_at=updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        current_revision = await db.scalar(select(ScheduledJobModel.revision).where(ScheduledJobModel.id == automation_id))
        if current_revision is None:
            raise HTTPException(status_code=404, detail="Automation not found.")
        raise HTTPException(status_code=409, detail={"code": "AutomationRevisionConflict", "message": "Automation changed since it was loaded.", "current_revision": current_revision})
    await db.commit()
    await db.refresh(job)
    latest = await _latest_executions(db, [job])
    return _automation_response(job).model_copy(update={"latest_execution": latest.get(job.id)})


@router.post("/{automation_id}/duplicate", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def duplicate_automation(
    automation_id: str,
    body: AutomationDuplicateWrite | None = None,
    db: AsyncSession = Depends(get_db),
) -> AutomationResponse:
    source = await db.get(ScheduledJobModel, automation_id)
    if source is None or (source.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")

    metadata = dict(source.metadata_json or {})
    instruction = metadata.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise HTTPException(status_code=409, detail="Automation instruction is unavailable.")
    try:
        interval_seconds = max(60, int(float(source.schedule_expression)))
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="Automation interval is invalid.")
    name = (body.name if body is not None and body.name is not None else f"{source.name} copy").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Automation name must not be blank.")

    source_project_name = metadata.get("project_name")
    project_name = source_project_name.strip() if isinstance(source_project_name, str) and source_project_name.strip() else None
    scope_value = metadata.get("scope")
    scope = scope_value if isinstance(scope_value, str) and scope_value in {"global", "project"} else "global"
    if scope == "project" and not project_name:
        raise HTTPException(status_code=409, detail="Automation project scope is unavailable.")
    now = utc_now()
    schedule = AutomationSchedule.model_validate(metadata.get("schedule", {}))
    duplicate = ScheduledJobModel(
        name=name,
        job_type=JobType.RECURRING.value,
        schedule_expression=str(interval_seconds),
        payload_json={},
        is_active=False,
        next_run_at=next_automation_run(schedule, now, interval_seconds),
        metadata_json={},
    )
    db.add(duplicate)
    await db.flush()
    duplicate_session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-automation-session:{duplicate.id}"))
    duplicate.payload_json = {
        "message": instruction.strip(),
        "session_id": duplicate_session_id,
        "project_name": project_name if scope == "project" else None,
        "automation_id": duplicate.id,
    }
    duplicate.metadata_json = {
        "kind": "automation",
        "description": metadata.get("description", "") if isinstance(metadata.get("description", ""), str) else "",
        "instruction": instruction.strip(),
        "scope": scope,
        "project_name": project_name if scope == "project" else None,
        "schedule": schedule.model_dump(),
    }
    await db.commit()
    await db.refresh(duplicate)
    return _automation_response(duplicate)


@router.post("/{automation_id}/archive", response_model=AutomationResponse)
async def archive_automation(automation_id: str, body: AutomationRevisionWrite, db: AsyncSession = Depends(get_db)) -> AutomationResponse:
    return await _set_archived_state(automation_id, True, body.expected_revision, db)


@router.post("/{automation_id}/restore", response_model=AutomationResponse)
async def restore_automation(automation_id: str, body: AutomationRevisionWrite, db: AsyncSession = Depends(get_db)) -> AutomationResponse:
    return await _set_archived_state(automation_id, False, body.expected_revision, db)


@router.post("/{automation_id}/run", response_model=AutomationRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_automation_now(automation_id: str, db: AsyncSession = Depends(get_db)) -> AutomationRunResponse:
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation" or (job.metadata_json or {}).get("archived") is True:
        raise HTTPException(status_code=404, detail="Automation not found.")
    if not job.is_active:
        raise HTTPException(status_code=409, detail="Paused automations cannot be run.")

    claim_token = await _claim_automation_dispatch(db, automation_id, "manual")
    if claim_token is None:
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
        await _release_automation_dispatch(db, automation_id, claim_token)

@router.get("/{automation_id}/runs", response_model=list[AutomationExecutionResponse])
async def list_automation_runs(
    automation_id: str,
    response: Response,
    cursor: str | None = Query(default=None, max_length=512),
    page_size: int | None = Query(default=None, ge=1, le=50),
    limit: int | None = Query(default=None, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[AutomationExecutionResponse]:
    """Return a bounded page of safe run summaries without exposing run content."""
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")

    page_limit = page_size if page_size is not None else limit if limit is not None else 10
    query = select(EventRecordModel).where(
        EventRecordModel.correlation_id == automation_id,
        EventRecordModel.event_type.in_({"timer.fired", "cron.tick", EventType.WEBHOOK_RECEIVED.value}),
    )
    if cursor is not None:
        cursor_timestamp, cursor_id = decode_timestamp_id_cursor(cursor)
        query = query.where(
            or_(
                EventRecordModel.occurred_at < cursor_timestamp,
                and_(EventRecordModel.occurred_at == cursor_timestamp, EventRecordModel.id < cursor_id),
            )
        )
    result = await db.execute(
        query.order_by(EventRecordModel.occurred_at.desc(), EventRecordModel.id.desc()).limit(page_limit + 1)
    )
    events = set_next_cursor_header(
        response,
        list(result.scalars()),
        page_limit,
        timestamp_for=lambda event: event.occurred_at,
        id_for=lambda event: event.id,
    )
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
        EventStatus.CANCELLED.value: "cancelled",
        EventStatus.FAILED.value: "failed",
        EventStatus.DEAD_LETTER.value: "dead_letter",
    }
    return [
        AutomationExecutionResponse(
            event_id=event.id,
            run_id=run_id,
            queued_at=event.occurred_at,
            status=(
                "dead_letter"
                if event.status == EventStatus.DEAD_LETTER.value
                else runs[run_id].status if run_id in runs else event_status.get(event.status, event.status)
            ),
            retry_count=event.retry_count,
            trigger_type=_automation_trigger_type(event.event_type, event.source),
            retry_of_event_id=(
                event.payload_json.get("retry_of_event_id")
                if isinstance(event.payload_json, dict) and isinstance(event.payload_json.get("retry_of_event_id"), str)
                else None
            ),
        )
        for event, run_id in zip(events, run_ids)
    ]


@router.post("/{automation_id}/runs/{event_id}/cancel", response_model=AutomationExecutionResponse)
async def cancel_queued_automation_run(
    automation_id: str,
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> AutomationExecutionResponse:
    """Cancel an outbox event only while it is still pending and unclaimed."""
    job = await db.get(ScheduledJobModel, automation_id)
    if job is None or (job.metadata_json or {}).get("kind") != "automation":
        raise HTTPException(status_code=404, detail="Automation not found.")
    event_filter = and_(
        EventRecordModel.id == event_id,
        EventRecordModel.correlation_id == automation_id,
        EventRecordModel.event_type.in_({"timer.fired", "cron.tick", EventType.WEBHOOK_RECEIVED.value}),
    )
    result = await db.execute(select(EventRecordModel).where(event_filter))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Automation run not found.")
    if event.status != EventStatus.CANCELLED.value:
        cancelled = await db.execute(
            update(EventRecordModel)
            .where(
                event_filter,
                EventRecordModel.status == EventStatus.PENDING.value,
                EventRecordModel.locked_at.is_(None),
                EventRecordModel.locked_by.is_(None),
            )
            .values(
                status=EventStatus.CANCELLED.value,
                processed_at=utc_now(),
                next_attempt_at=None,
                locked_at=None,
                locked_by=None,
                error_message="Cancelled by user before execution started.",
            )
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        if not cancelled.rowcount:
            current_result = await db.execute(
                select(EventRecordModel).where(event_filter).execution_options(populate_existing=True)
            )
            event = current_result.scalar_one_or_none()
            if event is None:
                raise HTTPException(status_code=404, detail="Automation run not found.")
            if event.status != EventStatus.CANCELLED.value:
                raise HTTPException(status_code=409, detail="Only queued automation runs can be cancelled.")
        else:
            await db.refresh(event)

    return AutomationExecutionResponse(
        event_id=event.id,
        run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{event.id}")),
        queued_at=event.occurred_at,
        status="cancelled",
        retry_count=event.retry_count,
        trigger_type=_automation_trigger_type(event.event_type, event.source),
        retry_of_event_id=(
            event.payload_json.get("retry_of_event_id")
            if isinstance(event.payload_json, dict) and isinstance(event.payload_json.get("retry_of_event_id"), str)
            else None
        ),
    )


@router.post("/{automation_id}/runs/{event_id}/retry", response_model=AutomationExecutionResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_automation_run(
    automation_id: str,
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> AutomationExecutionResponse:
    """Queue a fresh run from the saved instruction after a failed execution."""
    result = await db.execute(
        select(ScheduledJobModel)
        .where(ScheduledJobModel.id == automation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    job = result.scalar_one_or_none()
    if job is None or (job.metadata_json or {}).get("kind") != "automation" or (job.metadata_json or {}).get("archived") is True:
        raise HTTPException(status_code=404, detail="Automation not found.")
    if not job.is_active:
        raise HTTPException(status_code=409, detail="Paused automations cannot be retried.")
    source_event = await db.scalar(
        select(EventRecordModel).where(
            EventRecordModel.id == event_id,
            EventRecordModel.correlation_id == automation_id,
            EventRecordModel.event_type.in_({"timer.fired", "cron.tick", EventType.WEBHOOK_RECEIVED.value}),
        )
    )
    if source_event is None:
        raise HTTPException(status_code=404, detail="Automation run not found.")
    source_run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{source_event.id}"))
    source_run = await db.get(RunModel, source_run_id)
    can_retry = source_event.status in {EventStatus.FAILED.value, EventStatus.DEAD_LETTER.value} or (
        source_event.status == EventStatus.PROCESSED.value
        and source_run is not None
        and source_run.status == RunStatus.FAILED.value
    )
    if not can_retry:
        raise HTTPException(status_code=409, detail="Only failed or dead-lettered runs can be retried.")
    if await persistent_scheduler.has_active_automation_execution(db, job):
        raise HTTPException(status_code=409, detail="This automation already has a run awaiting execution or completion.")
    claim_token = await _claim_automation_dispatch(db, automation_id, "retry")
    if claim_token is None:
        raise HTTPException(status_code=409, detail="The scheduler is already dispatching this automation.")
    try:
        current = await db.execute(
            select(ScheduledJobModel)
            .where(ScheduledJobModel.id == automation_id)
            .execution_options(populate_existing=True)
        )
        job = current.scalar_one_or_none()
        if job is None or (job.metadata_json or {}).get("kind") != "automation" or (job.metadata_json or {}).get("archived") is True:
            raise HTTPException(status_code=404, detail="Automation not found.")
        if not job.is_active:
            raise HTTPException(status_code=409, detail="Paused automations cannot be retried.")
        if await persistent_scheduler.has_active_automation_execution(db, job):
            raise HTTPException(status_code=409, detail="This automation already has a run awaiting execution or completion.")

        saved_payload = job.payload_json if isinstance(job.payload_json, dict) else {}
        event = AURAEvent(
            event_type=EventType.TIMER_FIRED.value,
            source="automation_retry",
            payload={**saved_payload, "retry_of_event_id": source_event.id},
            correlation_id=job.id,
            idempotency_key=f"automation-retry-{job.id}-{source_event.id}-{uuid.uuid4()}",
        )
        queued = await event_bus.publish(event, db=db, dispatch_immediate=False)
        return AutomationExecutionResponse(
            event_id=queued.id,
            run_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura-event-run:{queued.id}")),
            queued_at=queued.occurred_at,
            status="queued",
            retry_count=0,
            trigger_type="retry",
            retry_of_event_id=source_event.id,
        )
    finally:
        await _release_automation_dispatch(db, automation_id, claim_token)

