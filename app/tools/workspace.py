"""Workspace filesystem tools strictly isolated to the configured sandbox root."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.approvals.capabilities import Capability
from app.core.errors import ToolExecutionError, WorkspaceEscapeError
from app.sandbox.workspace import resolve_workspace_path
from app.tools.base import RiskLevel, Tool, ToolResult

MAX_WORKSPACE_FILE_READ_BYTES = 256 * 1024
MAX_WORKSPACE_DIRECTORY_ENTRIES = 500


class ListWorkspaceFilesTool(Tool):
    """List files and directories inside the workspace sandbox."""

    @property
    def name(self) -> str:
        return "list_workspace_files"

    @property
    def description(self) -> str:
        return (
            f"List up to {MAX_WORKSPACE_DIRECTORY_ENTRIES} files and directories in the given workspace subpath. "
            "Choose a narrower subpath when a directory is larger."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.FILESYSTEM_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subpath": {
                    "type": "string",
                    "description": "Relative directory path to list (defaults to workspace root).",
                    "default": ".",
                }
            },
            "required": [],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        subpath = input_data.get("subpath", ".")
        try:
            target_dir = resolve_workspace_path(subpath)
            if not target_dir.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory '{subpath}' does not exist.",
                )
            if not target_dir.is_dir():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Path '{subpath}' is not a directory.",
                )

            entry_names = []
            with os.scandir(target_dir) as iterator:
                for entry in iterator:
                    entry_names.append(entry.name)
                    if len(entry_names) > MAX_WORKSPACE_DIRECTORY_ENTRIES:
                        return ToolResult(
                            success=False,
                            output="",
                            error=(
                                f"Directory contains more than {MAX_WORKSPACE_DIRECTORY_ENTRIES} entries; "
                                "list a narrower subpath."
                            ),
                        )

            entries = []
            for entry in sorted(entry_names):
                entry_path = target_dir / entry
                kind = "dir" if entry_path.is_dir() else "file"
                entries.append(f"[{kind}] {entry}")

            output = "\n".join(entries) if entries else "(empty directory)"
            return ToolResult(
                success=True,
                output=output,
                metadata={"count": len(entries), "path": str(subpath)},
            )
        except WorkspaceEscapeError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to list directory: {e}")


class ReadWorkspaceFileTool(Tool):
    """Read contents of a text file inside the workspace sandbox."""

    @property
    def name(self) -> str:
        return "read_workspace_file"

    @property
    def description(self) -> str:
        return (
            f"Read a regular UTF-8 file of up to {MAX_WORKSPACE_FILE_READ_BYTES} bytes "
            "located within the workspace."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.FILESYSTEM_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the file to read inside the workspace.",
                }
            },
            "required": ["path"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        path = input_data.get("path")
        if not path:
            return ToolResult(success=False, output="", error="Parameter 'path' is required.")

        try:
            target_file = resolve_workspace_path(path)
            if not target_file.exists():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File '{path}' does not exist in workspace.",
                )
            if not target_file.is_file():
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Target path '{path}' is not a regular file.",
                )

            with target_file.open("rb") as file_handle:
                content_bytes = file_handle.read(MAX_WORKSPACE_FILE_READ_BYTES + 1)
            if len(content_bytes) > MAX_WORKSPACE_FILE_READ_BYTES:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        f"File exceeds the {MAX_WORKSPACE_FILE_READ_BYTES}-byte read limit; "
                        "use a narrower file or inspect it through the sandbox."
                    ),
                )

            content = content_bytes.decode("utf-8", errors="replace")
            return ToolResult(
                success=True,
                output=content,
                metadata={"path": str(path), "bytes": len(content_bytes)},
            )
        except WorkspaceEscapeError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to read file: {e}")


class WriteWorkspaceFileTool(Tool):
    """Write contents to a file inside the workspace sandbox (requires approval)."""

    @property
    def name(self) -> str:
        return "write_workspace_file"

    @property
    def description(self) -> str:
        return "Write text contents to a file inside the workspace. Creates parent directories if needed."

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.FILESYSTEM_WRITE.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path of the file to write inside the workspace.",
                },
                "content": {
                    "type": "string",
                    "description": "Text contents to write to the file.",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        path = input_data.get("path")
        content = input_data.get("content", "")

        if not path:
            return ToolResult(success=False, output="", error="Parameter 'path' is required.")

        try:
            target_file = resolve_workspace_path(path)
            # Create parent directories safely
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")

            return ToolResult(
                success=True,
                output=f"Successfully wrote {len(content)} characters to '{path}'.",
                metadata={"path": str(path), "bytes_written": len(content)},
            )
        except WorkspaceEscapeError as e:
            return ToolResult(success=False, output="", error=str(e))
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Failed to write file: {e}")
