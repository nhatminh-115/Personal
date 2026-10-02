"""Deterministic safety checks for the live Context Bridge dogfood."""
import json
import os
import subprocess
import sys

from scripts.dogfood_context_bridge_live import (
    _safe_context_manifest,
    _safe_run_trace,
    live_environment_error,
)


def test_preflight_requires_openai_and_live_research_credentials():
    assert "MODEL_PROVIDER=openai" in live_environment_error({
        "MODEL_PROVIDER": "mock", "OPENAI_API_KEY": "secret", "RESEARCH_PROVIDER_MODE": "live"
    })
    assert "OPENAI_API_KEY" in live_environment_error({
        "MODEL_PROVIDER": "openai", "OPENAI_API_KEY": " ", "RESEARCH_PROVIDER_MODE": "live"
    })
    assert "RESEARCH_PROVIDER_MODE=live" in live_environment_error({
        "MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "configured", "RESEARCH_PROVIDER_MODE": "deterministic"
    })
    assert live_environment_error({
        "MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "configured", "RESEARCH_PROVIDER_MODE": "live"
    }) is None


def test_import_has_no_environment_or_filesystem_side_effects(tmp_path):
    code = (
        "import json, os, pathlib; before=dict(os.environ); "
        "import scripts.dogfood_context_bridge_live; "
        "print(json.dumps({'same_env': before == dict(os.environ), "
        "'db_files': [p.name for p in pathlib.Path.cwd().glob('*.db')]}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, text=True, capture_output=True, check=True
    )
    assert json.loads(completed.stdout) == {"same_env": True, "db_files": []}


def test_manifest_reports_bridge_only_and_omits_prompt_or_source_text():
    class Event:
        event_type = "context_compiled"
        payload = {
            "objects": [{
                "object_id": "bridge-1", "object_type": "context_bridge",
                "source_object_ids": ["claim-1", "evidence-1"],
                "selected_sections": {"conclusions": True, "artifacts": True},
            }],
            "estimated_tokens": 88,
            "prompt_text": "sensitive prompt text",
            "source_contents": ["sensitive source text"],
        }

    result = _safe_context_manifest([Event()], "bridge-1")
    assert result == {
        "objects": [{
            "object_id": "bridge-1", "object_type": "context_bridge",
            "source_object_ids": ["claim-1", "evidence-1"],
            "selected_sections": {"conclusions": True, "artifacts": True},
        }],
        "estimated_tokens": 88,
        "bridge_only": True,
    }
    assert "sensitive prompt text" not in repr(result)
    assert "sensitive source text" not in repr(result)


def test_run_trace_records_tool_names_and_failure_categories_only():
    class Event:
        def __init__(self, event_type, payload):
            self.event_type = event_type
            self.payload = payload

    result = _safe_run_trace([
        Event("tool_executed", {"tool": "research_search", "output": "private paper text"}),
        Event("tool_failed", {"tool": "read_document", "error": "private traceback", "error_category": "network"}),
        Event("run_failed", {"error": "private exception", "error_category": "graph_failure"}),
    ])
    assert result == {
        "tool_sequence": ["research_search"],
        "failures": [
            {"kind": "tool_failed", "category": "network"},
            {"kind": "run_failed", "category": "graph_failure"},
        ],
    }
    assert "private paper text" not in repr(result)
    assert "private traceback" not in repr(result)
