import json
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_tauri_csp_allows_sandboxed_blob_html_previews_without_inline_scripts() -> None:
    config_path = REPOSITORY_ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    directives = {
        parts[0]: parts[1:]
        for directive in config["app"]["security"]["csp"].split(";")
        if (parts := directive.strip().split())
    }

    assert directives["frame-src"] == ["'self'", "blob:"]
    assert "'unsafe-inline'" not in directives["script-src"]
    assert "'unsafe-eval'" not in directives["script-src"]
