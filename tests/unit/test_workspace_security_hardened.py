"""Unit tests for hardened workspace security, including symlink/junction escape prevention."""

import os
from pathlib import Path
import pytest

from app.core.errors import WorkspaceEscapeError
from app.sandbox.workspace import resolve_workspace_path


def test_absolute_path_outside_workspace_rejected(setup_test_workspace: Path):
    workspace = setup_test_workspace

    # Unix-like path or Windows root
    with pytest.raises(WorkspaceEscapeError) as exc_info:
        resolve_workspace_path("/etc/passwd", custom_root=workspace)
    assert "ACCESS DENIED" in str(exc_info.value)

    if os.name == "nt":
        with pytest.raises(WorkspaceEscapeError) as exc_info:
            resolve_workspace_path("C:\\Windows\\System32", custom_root=workspace)
        assert "ACCESS DENIED" in str(exc_info.value)


def test_deep_nested_traversal_rejected(setup_test_workspace: Path):
    workspace = setup_test_workspace

    with pytest.raises(WorkspaceEscapeError) as exc_info:
        resolve_workspace_path("folder1/folder2/../../../../escaped.txt", custom_root=workspace)
    assert "ACCESS DENIED" in str(exc_info.value)


def test_null_byte_injection_rejected(setup_test_workspace: Path):
    workspace = setup_test_workspace

    with pytest.raises(WorkspaceEscapeError) as exc_info:
        resolve_workspace_path("file.txt\0something", custom_root=workspace)
    assert "Null byte detected" in str(exc_info.value)


def test_symlink_or_junction_escape_rejected(setup_test_workspace: Path, tmp_path: Path):
    outside_dir = tmp_path / "sensitive_outside"
    outside_dir.mkdir()
    secret_file = outside_dir / "secret.env"
    secret_file.write_text("API_SECRET_KEY=12345", encoding="utf-8")

    workspace = setup_test_workspace
    link_target = workspace / "escape_link"

    # Create link: on Windows use junction if symlink not permitted; on Unix use os.symlink
    if os.name == "nt":
        import _winapi
        try:
            _winapi.CreateJunction(str(outside_dir), str(link_target))
        except Exception as e:
            pytest.skip(f"Junction creation not available: {e}")
    else:
        try:
            os.symlink(outside_dir, link_target)
        except OSError as e:
            pytest.skip(f"Symlinks not supported: {e}")

    # Attempt to resolve through the link pointing outside workspace
    with pytest.raises(WorkspaceEscapeError) as exc_info:
        resolve_workspace_path("escape_link/secret.env", custom_root=workspace)

    assert "ACCESS DENIED" in str(exc_info.value)
