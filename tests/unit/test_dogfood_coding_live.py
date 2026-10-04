"""Deterministic checks for the credential-gated coding dogfood harness."""
import json
import os
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager

import pytest

from app.db.models import RunModel, SessionModel

from scripts.dogfood_coding_impact_live import (
    _chat_request_payload,
    _latest_run_id_for_session,
    _safe_run_events,
    live_environment_error,
)


def test_preflight_requires_openai_and_never_accepts_mock():
    assert "MODEL_PROVIDER=openai" in live_environment_error({"MODEL_PROVIDER": "mock", "OPENAI_API_KEY": "secret"})
    assert "local model override" in live_environment_error({"MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "  "})
    assert live_environment_error({"MODEL_PROVIDER": "openai", "OPENAI_API_KEY": " configured "}) is None


def test_preflight_allows_only_explicit_ollama_models_on_loopback_without_cloud_credentials():
    local = {
        "MODEL_PROVIDER": "openai",
        "AURA_DOGFOOD_MODEL_OVERRIDE": "ollama:qwen2.5-coder:3b",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
    }
    assert live_environment_error(local) is None
    assert "ollama:model" in live_environment_error({
        **local,
        "AURA_DOGFOOD_MODEL_OVERRIDE": "openai:qwen2.5-coder:3b",
    })
    assert "loopback" in live_environment_error({**local, "OLLAMA_BASE_URL": "https://models.example.com"})


def test_chat_request_includes_only_explicit_local_model_override():
    without_override = _chat_request_payload("session-1", {})
    assert without_override["session_id"] == "session-1"
    assert "model_override" not in without_override

    with_override = _chat_request_payload(
        "session-2", {"AURA_DOGFOOD_MODEL_OVERRIDE": "ollama:qwen2.5-coder:3b"}
    )
    assert with_override["model_override"] == "ollama:qwen2.5-coder:3b"
    assert with_override["reasoning_override"] == "instant"


def test_import_does_not_mutate_environment_or_create_runtime_files(tmp_path):
    code = (
        "import json, os, pathlib; before=dict(os.environ); "
        "import scripts.dogfood_coding_impact_live; "
        "print(json.dumps({'same_env': before == dict(os.environ), "
        "'db_files': [p.name for p in pathlib.Path.cwd().glob('*.db')]}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, text=True, capture_output=True, check=True
    )
    assert json.loads(completed.stdout) == {"same_env": True, "db_files": []}


def test_audit_summary_records_tool_names_without_raw_outputs():
    class Event:
        def __init__(self, event_type, payload):
            self.event_type = event_type
            self.payload = payload

    result = _safe_run_events([
        Event("tool_executed", {"tool": "read_workspace_file", "result": {
            "success": True, "output": "sensitive source text", "metadata": {"path": "app/main.py"},
        }}),
        Event("tool_executed", {"tool": "sandbox_shell_execute", "result": {
            "success": False, "output": "private stderr", "error": "raw failure text",
        }}),
        Event("run_failed", {"error": "private exception", "error_category": "graph_failure"}),
    ])
    assert result == {
        "tool_sequence": ["read_workspace_file", "sandbox_shell_execute"],
        "artifacts": ["app/main.py"],
        "failures": [
            {"kind": "tool_execution", "tool": "sandbox_shell_execute"},
            {"kind": "run", "error_category": "graph_failure"},
        ],
    }
    assert "sensitive source text" not in repr(result)
    assert "private stderr" not in repr(result)


def test_pending_approvals_are_taken_from_persisted_approval_events():
    class Event:
        event_type = "approval_requested"
        payload = {"approval_id": "approval-child"}

    from scripts.dogfood_coding_impact_live import _pending_approval_ids

    assert _pending_approval_ids([Event()]) == ["approval-child"]


@pytest.mark.asyncio
async def test_dogfood_can_find_run_id_after_chat_returns_an_error(test_db_session, monkeypatch):
    session_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id))
    test_db_session.add(RunModel(id=run_id, session_id=session_id, user_message="Dogfood request"))
    await test_db_session.commit()

    @asynccontextmanager
    async def use_test_session():
        yield test_db_session

    from app.db import session as db_session
    monkeypatch.setattr(db_session, "async_session_factory", use_test_session)

    assert await _latest_run_id_for_session(session_id) == run_id
