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
