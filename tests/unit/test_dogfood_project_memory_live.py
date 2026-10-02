"""Deterministic safety checks for the project-memory live dogfood harness."""
import json
import os
import subprocess
import sys

from scripts.dogfood_project_memory_live import _context_summary, live_environment_error


def test_preflight_requires_real_openai_credentials():
    assert "MODEL_PROVIDER=openai" in live_environment_error({"MODEL_PROVIDER": "mock", "OPENAI_API_KEY": "secret"})
    assert "OPENAI_API_KEY" in live_environment_error({"MODEL_PROVIDER": "openai", "OPENAI_API_KEY": " "})
    assert live_environment_error({"MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "configured"}) is None


def test_import_has_no_environment_or_filesystem_side_effects(tmp_path):
    code = (
        "import json, os, pathlib; before=dict(os.environ); "
        "import scripts.dogfood_project_memory_live; "
        "print(json.dumps({'same_env': before == dict(os.environ), "
        "'db_files': [p.name for p in pathlib.Path.cwd().glob('*.db')]}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, text=True, capture_output=True, check=True
    )
    assert json.loads(completed.stdout) == {"same_env": True, "db_files": []}


def test_context_audit_proves_project_scoping_without_copying_memory_text():
    class Event:
        event_type = "context_loaded"
        payload = {
            "project_memory_ids": ["target-memory"],
            "project_facts": ["private project-memory source text"],
        }

    summary = _context_summary([Event()], "target-memory", "foreign-memory")
    assert summary == {
        "context_event_found": True,
        "target_memory_retrieved": True,
        "foreign_project_memory_retrieved": False,
        "project_memory_count": 1,
    }
    assert "private project-memory source text" not in repr(summary)


def test_missing_context_event_is_a_failed_retrieval():
    assert _context_summary([], "target-memory", "foreign-memory") == {
        "context_event_found": False,
        "target_memory_retrieved": False,
        "foreign_project_memory_retrieved": False,
        "project_memory_count": 0,
    }
