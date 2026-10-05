"""Shared startup helpers for scripts that import AURA from a source checkout."""

from pathlib import Path
import sys


def ensure_project_root(script_file: str | Path) -> Path:
    """Add the repository root derived from this script, independent of cwd."""
    project_root = Path(script_file).resolve().parents[1]
    root_entry = str(project_root)
    if root_entry in sys.path:
        sys.path.remove(root_entry)
    sys.path.insert(0, root_entry)
    return project_root
