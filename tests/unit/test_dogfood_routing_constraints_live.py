"""Deterministic catalog-truthfulness checks for routing dogfood."""
import json
import os
import subprocess
import sys

from scripts.dogfood_routing_constraints_live import _draft, configured_model, live_environment_error


def test_zero_invocation_preview_does_not_require_model_credentials():
    assert live_environment_error({}) is None
    assert live_environment_error({"MODEL_PROVIDER": "mock"}) is None
    assert live_environment_error({"MODEL_PROVIDER": "openai", "OPENAI_API_KEY": ""}) is None


def test_configured_model_uses_explicit_provider_kind_and_exact_catalog_id():
    providers = [
        {"id": "unknown-kind", "kind": "unknown", "available": True, "models": [{"id": "looks-local"}]},
        {"id": "offline-local", "kind": "local", "available": False, "models": [{"id": "offline"}]},
        {"id": "ollama", "kind": "local", "available": True, "models": [{"id": "qwen:latest"}]},
        {"id": "openai", "kind": "cloud", "available": True, "models": [{"id": "configured-model"}]},
    ]
    assert configured_model(providers, local=True) == ("ollama", "qwen:latest")
    assert configured_model(providers, local=False) == ("openai", "configured-model")


def test_unknown_or_unavailable_catalog_rows_are_not_guessed():
    assert configured_model([{"id": "local", "kind": "unknown", "available": True, "models": [{"id": "model"}]}], local=True) is None
    assert configured_model([{"id": "cloud", "kind": "cloud", "available": False, "models": [{"id": "model"}]}], local=False) is None


def test_routing_profile_draft_preserves_exact_provider_model_identity():
    draft = _draft("Local", "ollama:qwen:latest", "local_only", "none")
    route = draft["routes"]["root"]
    assert route["model_override"] == "ollama:qwen:latest"
    assert route.get("provider_override") is None
    assert route["reasoning"] == {"policy": "fixed", "effort": "instant"}


def test_import_does_not_create_runtime_state_or_change_environment(tmp_path):
    code = (
        "import json, os, pathlib; before=dict(os.environ); "
        "import scripts.dogfood_routing_constraints_live; "
        "print(json.dumps({'same_env': before == dict(os.environ), "
        "'db_files': [p.name for p in pathlib.Path.cwd().rglob('*.db')]}))"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.getcwd()
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, text=True, capture_output=True, check=True
    )
    assert json.loads(completed.stdout) == {"same_env": True, "db_files": []}
