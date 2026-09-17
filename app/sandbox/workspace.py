"""Workspace isolation and path traversal security guard."""

from pathlib import Path
from typing import Optional

from app.core.errors import WorkspaceEscapeError
from app.core.settings import settings


def resolve_workspace_path(subpath: str | Path, custom_root: Optional[Path] = None) -> Path:
    """
    Resolve and validate a path strictly within the designated workspace boundary.
    
    Raises:
        WorkspaceEscapeError: If the resolved path attempts to escape outside the workspace root.
    """
    root = (custom_root or settings.AURA_WORKSPACE_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)

    # Convert to string and clean whitespace
    subpath_str = str(subpath).strip()
    if not subpath_str:
        return root

    # Security: check for null byte injection
    if "\0" in subpath_str:
        raise WorkspaceEscapeError(f"ACCESS DENIED: Null byte detected in path '{subpath}'.")

    candidate_path = Path(subpath_str)
    if candidate_path.is_absolute():
        target_candidate = candidate_path.resolve()
    else:
        target_candidate = (root / candidate_path).resolve()

    # Verify that target_candidate is strictly within root (prevents symlink escapes and traversals)
    try:
        target_candidate.relative_to(root)
    except ValueError:
        raise WorkspaceEscapeError(
            f"ACCESS DENIED: Path traversal or symlink escape outside workspace boundary. Target: '{subpath}'"
        )

    return target_candidate
