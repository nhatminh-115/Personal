"""Integration tests for real filesystem tool execution inside workspace sandbox."""

from pathlib import Path
import pytest
from app.tools.workspace import (
    ListWorkspaceFilesTool,
    ReadWorkspaceFileTool,
    WriteWorkspaceFileTool,
)


@pytest.mark.asyncio
async def test_workspace_file_lifecycle(setup_test_workspace: Path):
    write_tool = WriteWorkspaceFileTool()
    read_tool = ReadWorkspaceFileTool()
    list_tool = ListWorkspaceFilesTool()

    # 1. Write file
    write_res = await write_tool.execute({
        "path": "notes/project.txt",
        "content": "AURA Phase 1 Integration Test",
    })
    assert write_res.success is True
    assert (setup_test_workspace / "notes/project.txt").exists()

    # 2. Read file
    read_res = await read_tool.execute({"path": "notes/project.txt"})
    assert read_res.success is True
    assert read_res.output == "AURA Phase 1 Integration Test"

    # 3. List workspace files
    list_res = await list_tool.execute({"subpath": "notes"})
    assert list_res.success is True
    assert "[file] project.txt" in list_res.output
