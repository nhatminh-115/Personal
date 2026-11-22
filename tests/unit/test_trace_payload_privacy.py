import pytest

from app.db.models import RunModel, SessionModel
from app.observability.tracer import TraceService


@pytest.mark.asyncio
async def test_trace_service_persists_and_logs_operational_metadata_only(test_db_session, monkeypatch):
    trace = TraceService(test_db_session)
    test_db_session.add(SessionModel(id="privacy-trace-session"))
    test_db_session.add(RunModel(
        id="privacy-trace-run", session_id="privacy-trace-session", user_message="private prompt marker",
    ))
    await test_db_session.commit()
    logged = []
    monkeypatch.setattr("app.observability.tracer.logger.info", lambda *args, **kwargs: logged.append((args, kwargs)))

    request = await trace.record_event(
        run_id="privacy-trace-run",
        session_id="privacy-trace-session",
        event_type="request_received",
        payload={"session_id": "privacy-trace-session", "message": "private prompt marker"},
    )
    tool = await trace.record_event(
        run_id="privacy-trace-run",
        session_id="privacy-trace-session",
        event_type="tool_executed",
        payload={
            "tool": "workspace.read",
            "tool_call_id": "call-private",
            "result": {
                "success": True,
                "output": "private tool output marker",
                "error": "private error marker",
                "metadata": {"path": "private/path marker", "bytes": 12},
            },
        },
    )

    assert request.payload == {"session_id": "privacy-trace-session"}
    assert tool.payload == {
        "tool": "workspace.read",
        "tool_call_id": "call-private",
        "result": {"success": True, "metadata": {"bytes": 12}},
    }
    for private_value in (
        "private prompt marker", "private tool output marker", "private error marker", "private/path marker",
    ):
        assert private_value not in str(logged)


@pytest.mark.asyncio
async def test_trace_keeps_allowlisted_research_provider_failure_metadata_only(test_db_session):
    trace = TraceService(test_db_session)
    test_db_session.add(SessionModel(id="research-error-trace-session"))
    test_db_session.add(RunModel(
        id="research-error-trace-run",
        session_id="research-error-trace-session",
        user_message="private search request",
    ))
    await test_db_session.commit()

    event = await trace.record_event(
        run_id="research-error-trace-run",
        session_id="research-error-trace-session",
        event_type="tool_executed",
        payload={
            "tool": "research_search",
            "result": {
                "success": False,
                "error": "private query and provider response",
                "metadata": {
                    "error_code": "research_providers_unavailable",
                    "failed_providers": ["Semantic Scholar", "arXiv", "Crossref", "attacker supplied provider"],
                    "query": "private query text",
                    "response_body": "private response body",
                },
            },
        },
    )

    assert event.payload["result"]["metadata"] == {
        "error_code": "research_providers_unavailable",
        "failed_providers": ["Semantic Scholar", "arXiv", "Crossref"],
    }
    assert "private query" not in str(event.payload)
    assert "private response body" not in str(event.payload)

    privacy_event = await trace.record_event(
        run_id="research-error-trace-run",
        session_id="research-error-trace-session",
        event_type="tool_executed",
        payload={
            "tool": "research_search",
            "result": {
                "success": False,
                "error": "private query was blocked",
                "metadata": {
                    "error_code": "privacy_boundary_violation",
                    "query": "private query text",
                },
            },
        },
    )
    assert privacy_event.payload["result"]["metadata"] == {
        "error_code": "privacy_boundary_violation",
    }
    assert "private query" not in str(privacy_event.payload)

    success_event = await trace.record_event(
        run_id="research-error-trace-run",
        session_id="research-error-trace-session",
        event_type="tool_executed",
        payload={
            "tool": "research_search",
            "result": {
                "success": True,
                "metadata": {
                    "error_code": "research_providers_unavailable",
                    "failed_providers": ["Semantic Scholar"],
                },
            },
        },
    )
    assert "metadata" not in success_event.payload["result"]


@pytest.mark.asyncio
async def test_context_manifest_keeps_provenance_and_metrics_without_object_text(test_db_session):
    trace = TraceService(test_db_session)
    test_db_session.add(SessionModel(id="context-trace-session"))
    test_db_session.add(RunModel(id="context-trace-run", session_id="context-trace-session", user_message="question"))
    await test_db_session.commit()
    event = await trace.record_event(
        run_id="context-trace-run",
        session_id="context-trace-session",
        event_type="context_compiled",
        payload={
            "estimated_tokens": 24,
            "character_count": 91,
            "prompt_text": "private compiled context marker",
            "objects": [{
                "object_id": "object-1",
                "object_type": "manual_note",
                "selected_by_user": True,
                "content": "private note marker",
                "source_object_ids": ["source-1"],
            }],
        },
    )

    assert event.payload == {
        "estimated_tokens": 24,
        "character_count": 91,
        "objects": [{
            "object_id": "object-1",
            "object_type": "manual_note",
            "selected_by_user": True,
            "source_object_ids": ["source-1"],
        }],
    }
    assert "private compiled context marker" not in str(event.payload)
    assert "private note marker" not in str(event.payload)


@pytest.mark.asyncio
async def test_context_loaded_trace_keeps_tiered_memory_ids_without_memory_text(test_db_session):
    trace = TraceService(test_db_session)
    test_db_session.add(SessionModel(id="memory-trace-session"))
    test_db_session.add(RunModel(id="memory-trace-run", session_id="memory-trace-session", user_message="question"))
    await test_db_session.commit()
    event = await trace.record_event(
        run_id="memory-trace-run",
        session_id="memory-trace-session",
        event_type="context_loaded",
        payload={
            "profile_memory_ids": {"work_style": "profile-memory"},
            "project_memory_ids": ["project-memory"],
            "semantic_memory_ids": [["semantic-memory"]],
            "episode_memory_ids": ["episode-memory"],
            "memory_privacy_sources": [{"memory_id": "project-memory", "privacy_policy": "confidential"}],
            "memory_text": "private remembered content must never appear in traces",
        },
    )

    assert event.payload == {
        "profile_memory_ids": ["profile-memory"],
        "project_memory_ids": ["project-memory"],
        "semantic_memory_ids": ["semantic-memory"],
        "episode_memory_ids": ["episode-memory"],
        "memory_privacy_sources": [{"memory_id": "project-memory", "privacy_policy": "confidential"}],
    }
    assert "private remembered content" not in str(event.payload)


@pytest.mark.asyncio
async def test_context_package_manifest_persists_budget_and_provenance_without_source_content(test_db_session):
    trace = TraceService(test_db_session)
    test_db_session.add(SessionModel(id="context-package-session"))
    test_db_session.add(RunModel(id="context-package-run", session_id="context-package-session", user_message="question"))
    await test_db_session.commit()
    secret = "private selected file text must never enter the context trace"
    event = await trace.record_event(
        run_id="context-package-run",
        session_id="context-package-session",
        event_type="context_package_compiled",
        payload={
            "version": 1,
            "budget": {
                "model_context_window": 32_000,
                "effective_context_window": 32_000,
                "context_window_source": "model_metadata",
                "tokenizer": "utf8-bytes-ceil-div-3",
                "system_tokens": 100,
                "tool_tokens": 80,
                "user_tokens": 20,
                "conversation_tokens": 200,
                "reserved_output_tokens": 2_000,
                "safety_margin_tokens": 3_200,
                "available_context_tokens": 26_420,
                "estimated_context_tokens": 120,
                "remaining_context_tokens": 26_300,
            },
            "candidate_count": 2,
            "included_item_count": 1,
            "excluded_item_count": 1,
            "selected_item_ids": ["workspace:note-1"],
            "priority_classes": {"explicit_selection": ["workspace:note-1"]},
            "scores": {"workspace:note-1": {"weighted_total": 0.75, "priority_class": "explicit_selection"}},
            "included_objects": [{
                "item_id": "workspace:note-1",
                "source_type": "manual_note",
                "source_id": "note-1",
                "object_id": "note-1",
                "project_id": "AURA",
                "priority_class": "explicit_selection",
                "estimated_tokens": 120,
                "source_object_ids": ["memory:source-1"],
                "selected_by_user": True,
                "content": secret,
            }],
            "exclusions": [{"item_id": "memory:old-1", "reason": "lower_priority", "content": secret}],
            "transformations": [],
            "privacy_requirement": "internal",
            "prompt_text": secret,
        },
    )

    assert event.payload["budget"]["effective_context_window"] == 32_000
    assert event.payload["budget"]["estimated_context_tokens"] == 120
    assert event.payload["budget"]["tokenizer"] == "utf8-bytes-ceil-div-3"
    assert event.payload["included_objects"][0]["object_id"] == "note-1"
    assert event.payload["included_objects"][0]["estimated_tokens"] == 120
    assert event.payload["exclusions"] == [{"item_id": "memory:old-1", "reason": "lower_priority"}]
    assert secret not in str(event.payload)


@pytest.mark.asyncio
async def test_run_recovery_trace_keeps_only_safe_lifecycle_metadata(test_db_session):
    trace = TraceService(test_db_session)
    test_db_session.add(SessionModel(id="recovery-trace-session"))
    test_db_session.add(RunModel(
        id="recovery-trace-run",
        session_id="recovery-trace-session",
        user_message="private prompt",
    ))
    await test_db_session.commit()

    started = await trace.record_event(
        run_id="recovery-trace-run",
        session_id="recovery-trace-session",
        event_type="run_executor_started",
        payload={"source": "event", "message": "private prompt"},
    )
    recovered = await trace.record_event(
        run_id="recovery-trace-run",
        session_id="recovery-trace-session",
        event_type="run_recovered",
        payload={
            "recovery_action": "completed",
            "source": "terminal_checkpoint",
            "decision_id": "private-decision-id",
        },
    )
    interrupted = await trace.record_event(
        run_id="recovery-trace-run",
        session_id="recovery-trace-session",
        event_type="run_interrupted",
        payload={
            "recovery_action": "failed_safe",
            "error_category": "executor_lost",
            "details": "private tool input",
        },
    )

    assert started.payload == {"source": "event"}
    assert recovered.payload == {"recovery_action": "completed", "source": "terminal_checkpoint"}
    assert interrupted.payload == {"recovery_action": "failed_safe", "error_category": "executor_lost"}
    assert "private" not in str([started.payload, recovered.payload, interrupted.payload])
