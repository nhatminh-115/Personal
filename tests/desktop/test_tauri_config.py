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


def test_windows_branding_uses_kuractus_install_identity_and_preserves_legacy_data_ids() -> None:
    config_path = REPOSITORY_ROOT / "desktop" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    nsis = config["bundle"]["windows"]["nsis"]
    hooks_path = config_path.parent / nsis["installerHooks"]
    hooks = hooks_path.read_text(encoding="utf-8")

    assert config["productName"] == "Kuractus"
    assert config["identifier"] == "com.aura.personal.desktop"
    assert nsis["installMode"] == "currentUser"
    assert 'FindProcessCurrentUser "$R1"' in hooks
    assert 'StrCpy $R1 "aura-desktop.exe"' in hooks
    assert 'StrCpy $R1 "kuractus-desktop.exe"' in hooks
    assert 'Delete "$SMPROGRAMS\\AURA.lnk"' in hooks
    assert 'Delete "$DESKTOP\\AURA.lnk"' in hooks
    assert "RmDir /r" not in hooks
    assert '"DisplayName" "Kuractus"' in hooks

    runtime_path = config_path.parent / "src" / "runtime.rs"
    runtime = runtime_path.read_text(encoding="utf-8")
    assert '.join("AURA")' in runtime
    assert 'const COMPOSE_PROJECT: &str = "aura-desktop"' in runtime

    cargo_manifest = (config_path.parent / "Cargo.toml").read_text(encoding="utf-8")
    assert 'name = "kuractus-desktop"' in cargo_manifest
    assert '"binaries/kuractus-api.exe": "kuractus-api.exe"' in config_path.read_text(encoding="utf-8")

    compose = (config_path.parent.parent / "runtime" / "compose.yaml").read_text(encoding="utf-8")
    assert "name: aura_desktop_postgres_data" in compose
