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

    # Convert to string and clean leading slashes/backslashes to ensure proper relative resolution
    subpath_str = str(subpath).strip()
    if not subpath_str:
        return root

    # Resolve target candidate relative to workspace root
    target_candidate = (root / subpath_str).resolve()

    # Verify that target_candidate is strictly within root
    try:
        target_candidate.relative_to(root)
    except ValueError:
        raise WorkspaceEscapeError(
            f"ACCESS DENIED: Path traversal outside workspace boundary. Target: '{subpath}'"
        )

    return target_candidate
