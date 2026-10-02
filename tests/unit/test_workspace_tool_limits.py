"""Bound workspace tool output to keep tool calls resource-safe."""

import os

import pytest

from app.core.settings import settings
from app.tools.workspace import (
    MAX_WORKSPACE_DIRECTORY_ENTRIES,
    MAX_WORKSPACE_FILE_READ_BYTES,
    ListWorkspaceFilesTool,
    ReadWorkspaceFileTool,
)


@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AURA_WORKSPACE_ROOT", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_workspace_read_accepts_file_at_byte_limit(workspace_root):
    content = b"a" * MAX_WORKSPACE_FILE_READ_BYTES
    (workspace_root / "large.txt").write_bytes(content)

    result = await ReadWorkspaceFileTool().execute({"path": "large.txt"})

    assert result.success is True
    assert len(result.output.encode("utf-8")) == MAX_WORKSPACE_FILE_READ_BYTES
    assert result.metadata["bytes"] == MAX_WORKSPACE_FILE_READ_BYTES


@pytest.mark.asyncio
async def test_workspace_read_rejects_file_over_byte_limit(workspace_root):
    (workspace_root / "too-large.txt").write_bytes(b"a" * (MAX_WORKSPACE_FILE_READ_BYTES + 1))

    result = await ReadWorkspaceFileTool().execute({"path": "too-large.txt"})

    assert result.success is False
    assert result.output == ""
    assert "read limit" in result.error


@pytest.mark.asyncio
async def test_workspace_read_rejects_non_regular_files(workspace_root):
    if not hasattr(os, "mkfifo"):
        pytest.skip("Named pipes are not supported on this platform")
    fifo_path = workspace_root / "stream"
    os.mkfifo(fifo_path)

    result = await ReadWorkspaceFileTool().execute({"path": "stream"})

    assert result.success is False
    assert "not a regular file" in result.error


@pytest.mark.asyncio
async def test_workspace_listing_rejects_directory_over_entry_limit(workspace_root):
    for index in range(MAX_WORKSPACE_DIRECTORY_ENTRIES + 1):
        (workspace_root / f"entry-{index:04}.txt").touch()

    result = await ListWorkspaceFilesTool().execute({"subpath": "."})

    assert result.success is False
    assert result.output == ""
    assert "narrower subpath" in result.error
