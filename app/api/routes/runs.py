"""Runs and trace auditing endpoint: GET /v1/runs/{id}."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_trace_service
from app.api.pagination import decode_timestamp_id_cursor, set_next_cursor_header
from app.api.schemas import ResearchInspectorResponse, RunDetailResponse, RunEventResponse
from app.db.models import DelegationModel, RunModel, RunEventModel
from app.db.session import get_db
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.memory.context_compiler import PRIVACY_REQUIREMENT_ORDER

router = APIRouter(prefix="/v1/runs", tags=["Runs"])


def _safe_event_payload(event_type: str, payload: object) -> dict:
    """Project persisted trace data to operational metadata safe for the UI."""
    if not isinstance(payload, dict):
        return {}

    def pick(source: dict, keys: tuple[str, ...]) -> dict:
        return {key: source[key] for key in keys if key in source}

    if event_type == "request_received":
        return pick(payload, ("session_id", "parent_run_id", "specialist", "trigger_event_id"))
    if event_type == "routing_profile_resolved":
        return pick(payload, (
            "profile_id", "profile_version", "winning_scope", "role", "is_lock_all",
            "privacy_policy", "fallback_policy", "explicit_model_override",
            "reasoning_policy", "reasoning_effort",
        ))
    if event_type == "context_loaded":
        safe = pick(payload, ("context_count", "history_length", "compiled_object_count"))
        raw_profile_ids = payload.get("profile_memory_ids")
        if isinstance(raw_profile_ids, dict):
            safe["profile_memory_ids"] = list(dict.fromkeys(
                value for value in raw_profile_ids.values() if isinstance(value, str) and value
            ))[:128]
        for field in ("project_memory_ids", "episode_memory_ids"):
            values = payload.get(field)
            if isinstance(values, list):
                safe[field] = list(dict.fromkeys(value for value in values if isinstance(value, str) and value))[:128]
        raw_semantic_ids = payload.get("semantic_memory_ids")
        if isinstance(raw_semantic_ids, list):
            safe["semantic_memory_ids"] = list(dict.fromkeys(
                value for group in raw_semantic_ids if isinstance(group, list)
                for value in group if isinstance(value, str) and value
            ))[:128]
        raw_sources = payload.get("memory_privacy_sources")
        if isinstance(raw_sources, list):
            safe["memory_privacy_sources"] = [
                {"memory_id": item["memory_id"], "privacy_policy": item["privacy_policy"]}
                for item in raw_sources
                if isinstance(item, dict)
                and isinstance(item.get("memory_id"), str)
                and isinstance(item.get("privacy_policy"), str)
                and item["privacy_policy"] in PRIVACY_REQUIREMENT_ORDER
            ]
        return safe
    if event_type == "context_compiled":
        safe_objects = []
        raw_objects = payload.get("objects")
        if isinstance(raw_objects, list):
            for item in raw_objects:
                if not isinstance(item, dict):
                    continue
                object_id, object_type = item.get("object_id"), item.get("object_type")
                if not isinstance(object_id, str) or not isinstance(object_type, str):
                    continue
                safe_item = {
                    "object_id": object_id,
                    "object_type": object_type,
                    "selected_by_user": item.get("selected_by_user") is True,
                }
                source_ids = item.get("source_object_ids")
                if isinstance(source_ids, list):
                    safe_item["source_object_ids"] = [value for value in source_ids if isinstance(value, str)]
                selected_sections = item.get("selected_sections")
                if isinstance(selected_sections, dict):
                    safe_item["selected_sections"] = {
                        key: value for key, value in selected_sections.items()
                        if isinstance(key, str) and (isinstance(value, bool) or value is None)
                    }
                safe_objects.append(safe_item)
        safe = pick(payload, (
            "estimated_tokens", "character_count", "privacy_requirement", "required_capabilities",
            "capability_requirements", "required_tool_capabilities", "resolved_tool_names",
        ))
        if isinstance(safe.get("required_capabilities"), list):
            safe["required_capabilities"] = [value for value in safe["required_capabilities"] if isinstance(value, str)]
        for key in ("required_tool_capabilities", "resolved_tool_names"):
            if isinstance(safe.get(key), list):
                safe[key] = [value for value in safe[key] if isinstance(value, str)]
            else:
                safe.pop(key, None)
        requirements = safe.get("capability_requirements")
        if isinstance(requirements, dict):
            safe["capability_requirements"] = pick(requirements, (
                "requires_tools", "requires_vision", "requires_structured_output", "requires_long_context",
            ))
        else:
            safe.pop("capability_requirements", None)
        raw_privacy_sources = payload.get("privacy_sources")
        if isinstance(raw_privacy_sources, list):
            safe["privacy_sources"] = [
                {"object_id": item["object_id"], "privacy_policy": item["privacy_policy"]}
                for item in raw_privacy_sources
                if isinstance(item, dict)
                and isinstance(item.get("object_id"), str)
                and isinstance(item.get("privacy_policy"), str)
                and item["privacy_policy"] in PRIVACY_REQUIREMENT_ORDER
            ]
        safe["objects"] = safe_objects
        return safe
    if event_type == "model_selected":
        return pick(payload, (
            "agent_role", "task_type", "provider", "model", "profile_id", "profile_version",
            "winning_scope", "selection_reason", "privacy", "fallback_policy", "context_window",
            "estimated_input_tokens", "reserved_output_tokens", "required_context_window", "required_capabilities", "requires_tools",
            "requires_vision", "requires_structured_output", "requires_long_context",
        ))
    if event_type == "reasoning_effort_selected":
        return pick(payload, ("policy_mode", "configured_bounds", "selected_effort"))
    if event_type == "fallback_considered":
        return pick(payload, ("fallback_policy", "primary_provider", "selected_provider", "candidate_model"))
    if event_type == "fallback_blocked":
        return pick(payload, ("policy", "error_type", "privacy_boundary", "proposed_provider", "proposed_model"))
    if event_type == "context_window_blocked":
        return pick(payload, ("provider", "model", "estimated_input_tokens", "reserved_output_tokens", "context_window"))
    if event_type == "model_called":
        safe = pick(payload, ("messages_count", "tools_count", "estimated_input_tokens", "context_window"))
        decision = payload.get("routing_decision")
        if isinstance(decision, dict):
            safe["routing_decision"] = pick(decision, ("provider", "model", "reason"))
        return safe
    if event_type == "response_generated":
        return pick(payload, ("response_length", "step"))
    if event_type == "tool_requested":
        return pick(payload, ("tool", "tool_name", "tool_call_id"))
    if event_type == "tool_executed":
        safe = pick(payload, ("tool", "tool_name", "tool_call_id", "step"))
        result = payload.get("result")
        if isinstance(result, dict):
            safe_result = pick(result, ("success", "error_category"))
            safe["result"] = safe_result
            if isinstance(safe_result.get("success"), bool):
                safe["status"] = "success" if safe_result["success"] else "failed"
        return safe
    if event_type == "approval_requested":
        return pick(payload, ("tool_name", "tool_call_id", "approval_id", "risk_level"))
    if event_type in {"approval_granted", "approval_rejected"}:
        return pick(payload, ("approval_id", "tool_call_id", "tool_name", "edited"))
    if event_type in {"delegation_started", "delegation_completed", "delegation_failed"}:
        return pick(payload, ("specialist", "child_run_id", "status", "steps"))
    if event_type == "step_completed":
        return pick(payload, ("step", "total_tool_calls", "consecutive_failures", "tool_results_count"))
    if event_type == "memory_updated":
        return pick(payload, ("memory_count", "project_name"))
    if event_type == "run_failed":
        return pick(payload, ("error_category",))
    if event_type in {"run_completed", "run_cancelled"}:
        return pick(payload, ("status",))
    return {}


@router.get("/{run_id}/routing")
async def get_run_routing(
    run_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return persisted routing decisions for a root run and its specialists."""
    root = await db.get(RunModel, run_id)
    if not root:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    runs_result = await db.execute(
        select(RunModel).where((RunModel.id == run_id) | (RunModel.parent_run_id == run_id))
    )
    runs = sorted(runs_result.scalars().all(), key=lambda run: (run.id != run_id, run.created_at, run.id))
    events_result = await db.execute(
        select(RunEventModel)
        .where(
            RunEventModel.run_id.in_([run.id for run in runs]),
            RunEventModel.event_type.in_({
                "model_selected",
                "reasoning_effort_selected",
                "context_compiled",
                "context_loaded",
                "fallback_considered",
                "fallback_blocked",
            }),
        )
        .order_by(RunEventModel.created_at, RunEventModel.id)
    )
    events_by_run: dict[str, list[RunEventModel]] = {run.id: [] for run in runs}
    for event in events_result.scalars().all():
        events_by_run[event.run_id].append(event)

    decisions = []
    for run in runs:
        events = events_by_run[run.id]
        selected = next((e.payload for e in reversed(events) if e.event_type == "model_selected"), None)
        reasoning = next((e.payload for e in reversed(events) if e.event_type == "reasoning_effort_selected"), None)
        context_manifest = next((e.payload for e in reversed(events) if e.event_type == "context_compiled"), None)
        context_loaded = next((e.payload for e in reversed(events) if e.event_type == "context_loaded"), None)
        safe_context_loaded = _safe_event_payload("context_loaded", context_loaded) if context_loaded is not None else {}
        decisions.append({
            "run_id": run.id,
            "parent_run_id": run.parent_run_id,
            "snapshot": run.routing_snapshot_json or {},
            "model_selection": _safe_event_payload("model_selected", selected) if selected is not None else None,
            "reasoning_selection": _safe_event_payload("reasoning_effort_selected", reasoning) if reasoning is not None else None,
            "context_manifest": _safe_event_payload("context_compiled", context_manifest) if context_manifest is not None else None,
            "memory_ids_by_tier": {
                tier: safe_context_loaded.get(f"{tier}_memory_ids", [])
                for tier in ("profile", "project", "semantic", "episode")
            },
            "memory_privacy_sources": safe_context_loaded.get("memory_privacy_sources", []),
            "fallback_events": [
                {"event_type": e.event_type, "payload": _safe_event_payload(e.event_type, e.payload)}
                for e in events if e.event_type in {"fallback_considered", "fallback_blocked"}
            ],
        })
    return {"run_id": run_id, "decisions": decisions}


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run_details(
    run_id: str,
    response: Response,
    page_size: int = Query(default=100, ge=1, le=500),
    cursor: str | None = None,
    trace_service: TraceService = Depends(get_trace_service),
    db: AsyncSession = Depends(get_db),
) -> RunDetailResponse:
    """Inspect run details and one bounded page of its chronological event trace."""
    run = await trace_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    query = select(RunEventModel).where(RunEventModel.run_id == run_id)
    if cursor:
        cursor_created_at, cursor_id = decode_timestamp_id_cursor(cursor)
        query = query.where(
            or_(
                RunEventModel.created_at > cursor_created_at,
                and_(RunEventModel.created_at == cursor_created_at, RunEventModel.id > cursor_id),
            )
        )
    result = await db.execute(
        query.order_by(RunEventModel.created_at.asc(), RunEventModel.id.asc()).limit(page_size + 1)
    )
    events = set_next_cursor_header(
        response, list(result.scalars().all()), page_size,
        lambda event: event.created_at, lambda event: event.id,
    )

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
                payload=_safe_event_payload(e.event_type, e.payload),
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
