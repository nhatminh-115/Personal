"""Generate the Windows app icon from the approved Kuractus artwork."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    repository = Path(__file__).resolve().parents[2]
    icon_source = repository / "desktop" / "src-tauri" / "icons" / "kuractus-icon.png"
    icon_directory = repository / "desktop" / "src-tauri" / "icons"
    tauri_cli = repository / "web" / "node_modules" / "@tauri-apps" / "cli" / "tauri.js"
    node = shutil.which("node")

    if not icon_source.is_file():
        raise SystemExit(f"Kuractus icon source does not exist: {icon_source}")
    if not tauri_cli.is_file():
        raise SystemExit("Install the locked web dependencies before generating the Windows icon.")
    if node is None:
        raise SystemExit("Node.js is required to generate the Windows icon.")

    with tempfile.TemporaryDirectory(prefix="kuractus-icon-") as temporary_directory:
        subprocess.run(
            [node, str(tauri_cli), "icon", str(icon_source), "--output", temporary_directory],
            cwd=repository,
            check=True,
        )

        generated = Path(temporary_directory)
        for name in ("icon.ico", "icon.png"):
            candidate = generated / name
            if not candidate.is_file():
                raise SystemExit(f"Tauri did not generate the expected icon: {candidate}")
            shutil.copyfile(candidate, icon_directory / name)


if __name__ == "__main__":
    main()
