"""Unit tests for workspace path isolation and security boundary."""

from pathlib import Path
import pytest
from app.core.errors import WorkspaceEscapeError
from app.sandbox.workspace import resolve_workspace_path


def test_valid_subpath_resolves_inside_workspace(tmp_path: Path):
    workspace = tmp_path / "sandbox"
    workspace.mkdir()

    resolved = resolve_workspace_path("subfolder/file.txt", custom_root=workspace)
    assert resolved == (workspace / "subfolder/file.txt").resolve()
    assert str(resolved).startswith(str(workspace.resolve()))


def test_relative_path_traversal_blocked(tmp_path: Path):
    workspace = tmp_path / "sandbox"
    workspace.mkdir()

    with pytest.raises(WorkspaceEscapeError) as exc_info:
        resolve_workspace_path("../../outside.txt", custom_root=workspace)

    assert "ACCESS DENIED" in str(exc_info.value)


def test_deep_path_traversal_blocked(tmp_path: Path):
    workspace = tmp_path / "sandbox"
    workspace.mkdir()

    with pytest.raises(WorkspaceEscapeError):
        resolve_workspace_path("folder/../../../../escape.txt", custom_root=workspace)


def test_root_path_resolves_to_workspace(tmp_path: Path):
    workspace = tmp_path / "sandbox"
    workspace.mkdir()

    resolved = resolve_workspace_path("", custom_root=workspace)
    assert resolved == workspace.resolve()
