from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.orchestrator.nodes import load_context_node


@pytest.mark.asyncio
async def test_context_loaded_trace_carries_memory_privacy_source_ids(monkeypatch):
    sources = [
        {"memory_id": "profile-memory-1", "privacy_policy": "local_only"},
        {"memory_id": "project-memory-2", "privacy_policy": "confidential"},
    ]

    class StubAssembler:
        def __init__(self, memory_service):
            self.memory_service = memory_service

        async def assemble_context(self, **kwargs):
            return SimpleNamespace(
                profile_memory_ids={"preference": "profile-memory-1"},
                project_memory_ids=["project-memory-2"],
                semantic_memory_ids=[],
                episode_memory_ids=[],
                privacy_requirement="local_only",
                privacy_memory_sources=sources,
                working_messages=[],
                episodes=[],
                format_for_system_prompt=lambda: "reference context",
            )

    monkeypatch.setattr("app.orchestrator.nodes.ContextAssembler", StubAssembler)
    trace = SimpleNamespace(record_event=AsyncMock())
    state = {
        "run_id": "run-privacy-trace",
        "session_id": "session-privacy-trace",
        "user_message": "Use the saved context.",
        "messages": [],
        "metadata": {},
    }

    result = await load_context_node(state, {
        "configurable": {
            "memory_service": object(),
            "trace_service": trace,
        },
    })

    context_events = [
        call.kwargs for call in trace.record_event.await_args_list
        if call.kwargs.get("event_type") == "context_loaded"
    ]
    assert len(context_events) == 1
    assert context_events[0]["payload"]["memory_privacy_sources"] == sources
    assert result["metadata"]["privacy_requirement"] == "local_only"
    assert "reference context" in result["retrieved_context"]
