"""Privacy-preserving projections for persisted operational run events."""

from typing import Any

SAFE_OPERATIONAL_ERROR_CODES = frozenset({"research_providers_unavailable"})
SAFE_RESEARCH_PROVIDER_NAMES = frozenset({"Semantic Scholar", "arXiv"})


def safe_operational_error_metadata(metadata: object) -> dict[str, Any]:
    """Project only explicitly approved, non-content tool failure metadata."""
    if not isinstance(metadata, dict) or metadata.get("error_code") not in SAFE_OPERATIONAL_ERROR_CODES:
        return {}
    safe: dict[str, Any] = {"error_code": metadata["error_code"]}
    failed_providers = metadata.get("failed_providers")
    if isinstance(failed_providers, list):
        providers = list(dict.fromkeys(
            name for name in failed_providers
            if isinstance(name, str) and name in SAFE_RESEARCH_PROVIDER_NAMES
        ))
        if providers:
            safe["failed_providers"] = providers
    return safe


def sanitize_trace_payload(event_type: str, payload: object) -> dict[str, Any]:
    """Keep operational provenance while excluding prompts, arguments, and content."""
    if not isinstance(payload, dict):
        return {}

    def pick(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        return {key: source[key] for key in keys if key in source}

    if event_type == "request_received":
        return pick(payload, ("session_id", "parent_run_id", "specialist", "trigger_event_id"))
    if event_type == "routing_profile_resolved":
        return pick(payload, (
            "profile_id", "profile_version", "winning_scope", "role", "is_lock_all",
            "privacy_policy", "fallback_policy", "explicit_model_override",
            "reasoning_policy", "reasoning_effort",
        ))
    if event_type == "model_selected":
        return pick(payload, (
            "agent_role", "task_type", "provider", "model", "profile_id", "profile_version",
            "winning_scope", "selection_reason", "privacy", "fallback_policy", "context_window",
            "estimated_input_tokens", "reserved_output_tokens", "required_context_window",
            "required_capabilities", "requires_tools", "requires_vision",
            "requires_structured_output", "requires_long_context",
        ))
    if event_type == "context_compiled":
        safe = pick(payload, (
            "estimated_tokens", "character_count", "privacy_requirement", "required_capabilities",
            "required_tool_capabilities", "resolved_tool_names",
        ))
        objects = payload.get("objects")
        if isinstance(objects, list):
            safe["objects"] = [
                {
                    "object_id": row["object_id"],
                    "object_type": row["object_type"],
                    "selected_by_user": row.get("selected_by_user") is True,
                    **({"source_object_ids": [value for value in row["source_object_ids"] if isinstance(value, str)]}
                       if isinstance(row.get("source_object_ids"), list) else {}),
                    **({"selected_sections": {
                        key: value for key, value in row["selected_sections"].items()
                        if isinstance(key, str) and (value is None or isinstance(value, bool))
                    }} if isinstance(row.get("selected_sections"), dict) else {}),
                }
                for row in objects[:128]
                if isinstance(row, dict)
                and isinstance(row.get("object_id"), str)
                and isinstance(row.get("object_type"), str)
            ]
        sources = payload.get("privacy_sources")
        if isinstance(sources, list):
            safe["privacy_sources"] = [
                {"object_id": row["object_id"], "privacy_policy": row["privacy_policy"]}
                for row in sources[:128]
                if isinstance(row, dict)
                and isinstance(row.get("object_id"), str)
                and isinstance(row.get("privacy_policy"), str)
            ]
        requirements = payload.get("capability_requirements")
        if isinstance(requirements, dict):
            safe["capability_requirements"] = pick(requirements, (
                "requires_tools", "requires_vision", "requires_structured_output", "requires_long_context",
            ))
        return safe
    if event_type == "context_loaded":
        safe = pick(payload, (
            "context_count", "history_length", "compiled_object_count",
            "project_memory_privacy", "memory_privacy_requirement",
        ))
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
        sources = payload.get("memory_privacy_sources")
        if isinstance(sources, list):
            safe["memory_privacy_sources"] = [
                {"memory_id": row["memory_id"], "privacy_policy": row["privacy_policy"]}
                for row in sources[:128]
                if isinstance(row, dict)
                and isinstance(row.get("memory_id"), str)
                and isinstance(row.get("privacy_policy"), str)
            ]
        return safe
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
            metadata = result.get("metadata")
            if isinstance(metadata, dict):
                safe_metadata = pick(metadata, ("artifact_id", "object_id", "bytes", "line_count", "exit_code"))
                safe_metadata.update(safe_operational_error_metadata(metadata))
                if safe_metadata:
                    safe_result["metadata"] = safe_metadata
            safe["result"] = safe_result
        return safe
    if event_type == "approval_requested":
        return pick(payload, ("tool_name", "tool_call_id", "approval_id", "risk_level"))
    if event_type in {"approval_granted", "approval_rejected"}:
        return pick(payload, ("approval_id", "tool_call_id", "tool_name", "edited"))
    if event_type in {"delegation_started", "delegation_completed", "delegation_failed"}:
        return pick(payload, ("specialist", "child_run_id", "status", "steps", "steps_taken"))
    if event_type.startswith("routing_confirmation_"):
        return pick(payload, (
            "confirmation_id", "execution_run_id", "proposed_provider", "proposed_model", "decision", "status",
        ))
    if event_type == "step_completed":
        return pick(payload, ("step", "total_tool_calls", "consecutive_failures", "tool_results_count"))
    if event_type == "memory_updated":
        return pick(payload, ("memory_count", "project_name"))
    if event_type == "automation_triggered":
        safe = pick(payload, ("trigger_event_id", "automation_id"))
        name = payload.get("automation_name")
        if isinstance(name, str):
            safe["automation_name"] = name[:120]
        return safe
    if event_type == "run_failed":
        return pick(payload, ("error_category",))
    if event_type in {"run_completed", "run_cancelled"}:
        return pick(payload, ("status",))
    return {}
