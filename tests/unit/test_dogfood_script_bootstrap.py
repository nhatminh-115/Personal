"""Dogfood entrypoints resolve AURA from their checkout rather than the caller's cwd."""

import sys
from pathlib import Path

from scripts._bootstrap import ensure_project_root, resolve_project_path


def test_dogfood_script_bootstrap_uses_script_location(monkeypatch, tmp_path: Path):
    script_file = Path(__file__).resolve().parents[2] / "scripts" / "dogfood_coding_impact_live.py"
    project_root = script_file.parents[1]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != str(project_root)])

    resolved = ensure_project_root(script_file)

    assert resolved == project_root
    assert sys.path[0] == str(project_root)


def test_dogfood_artifact_defaults_are_anchored_to_checkout(monkeypatch, tmp_path: Path):
    script_file = Path(__file__).resolve().parents[2] / "scripts" / "dogfood_coding_impact_live.py"
    project_root = script_file.parents[1]
    monkeypatch.chdir(tmp_path)

    assert resolve_project_path(project_root, ".aura_dogfood") == project_root / ".aura_dogfood"
    assert resolve_project_path(project_root, "artifacts/dogfood") == project_root / "artifacts" / "dogfood"


def test_dogfood_artifact_path_preserves_explicit_absolute_override(tmp_path: Path):
    override = tmp_path / "isolated-artifacts"

    assert resolve_project_path(Path("D:/checkout"), override) == override
