"""Prove a Docker Compose backup restores all three stores into fresh volumes.

This destructive acceptance runner is limited to the repository's CI Compose
project and the named local A6 dogfood project. It never targets a generic or
production Compose project.
"""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup_compose import create_backup, verify_backup
from scripts.restore_compose import restore_backup


ALLOWED_PROJECTS = {"aura-ci", "aura-a6-dogfood"}
CHECKPOINT_DATABASE = "/app/checkpoints/aura_checkpoints.db"
ABSENT_FILE_MARKER = "__AURA_A6_FILE_ABSENT__"


def validate_test_project(project_name: str, allow_volume_recreate: str) -> None:
    """Require explicit opt-in and an isolated project name before volume deletion."""
    if project_name not in ALLOWED_PROJECTS or allow_volume_recreate != "1":
        raise ValueError("Clean-volume recreation is allowed only for an explicitly enabled A6 test project")


def validate_workspace_path(value: str) -> PurePosixPath:
    """Accept only a relative workspace file path with no traversal syntax."""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or ":" in value
        or "\\" in value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("Workspace acceptance file must be a safe relative POSIX path")
    return path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _compose(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", "compose", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _api_request(api_base_url: str, path: str, token: str) -> tuple[int, dict | None]:
    url = urllib.parse.urljoin(api_base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read())
            return response.status, payload if isinstance(payload, dict) else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _wait_ready(api_base_url: str) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(api_base_url.rstrip("/") + "/ready", timeout=3) as response:
                payload = json.loads(response.read())
            if payload == {"status": "ready", "checks": {"database": "healthy", "checkpointer": "healthy"}}:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise RuntimeError("Kuractus Compose stack did not become ready")


def _run_details(api_base_url: str, token: str, run_id: str) -> dict:
    status, payload = _api_request(api_base_url, f"/v1/runs/{run_id}", token)
    if status != 200 or payload is None or payload.get("id") != run_id or payload.get("status") != "completed":
        raise RuntimeError("The representative run is missing or not completed")
    return payload


def _checkpoint_count(run_id: str) -> int:
    query = (
        "import pathlib, sqlite3, sys\n"
        f"path = pathlib.Path({CHECKPOINT_DATABASE!r})\n"
        "count = 0\n"
        "if path.is_file():\n"
        "    try:\n"
        "        with sqlite3.connect(path) as connection:\n"
        "            count = connection.execute(\n"
        "                'SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?', (sys.argv[1],)\n"
        "            ).fetchone()[0]\n"
        "    except sqlite3.OperationalError as exc:\n"
        "        if 'no such table' not in str(exc):\n"
        "            raise\n"
        "print(count)\n"
    )
    output = _compose("exec", "-T", "aura-app", "python", "-c", query, run_id).strip()
    return int(output)


def _model_provider() -> str:
    query = "from app.core.settings import settings; print(settings.MODEL_PROVIDER)"
    return _compose("exec", "-T", "aura-app", "python", "-c", query).strip()


def _workspace_file_bytes(path: PurePosixPath) -> bytes | None:
    query = (
        "from pathlib import Path; import base64, sys; "
        "path = Path('/app/workspace').joinpath(*sys.argv[1].split('/')); "
        f"print({ABSENT_FILE_MARKER!r}) if not path.is_file() else print(base64.b64encode(path.read_bytes()).decode('ascii'))"
    )
    output = _compose("exec", "-T", "aura-app", "python", "-c", query, path.as_posix()).strip()
    return None if output == ABSENT_FILE_MARKER else base64.b64decode(output, validate=True)


def _archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_acceptance(
    *,
    backup_path: Path,
    report_path: Path,
    api_base_url: str,
    api_token: str,
    run_id: str,
    workspace_path: str,
    expected_workspace_content: str,
) -> dict:
    project_name = os.environ.get("COMPOSE_PROJECT_NAME", "")
    validate_test_project(project_name, os.environ.get("AURA_DOGFOOD_ALLOW_VOLUME_RECREATE", ""))
    relative_workspace_path = validate_workspace_path(workspace_path)
    parsed_url = urllib.parse.urlparse(api_base_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("A6 acceptance must use the local Compose API")
    try:
        uuid.UUID(run_id)
    except ValueError as exc:
        raise ValueError("A6 acceptance run ID must be a UUID") from exc

    started_at = _utc_now()
    model_provider = _model_provider()
    if model_provider != "mock":
        raise RuntimeError("A6 acceptance requires the deterministic mock model provider")
    source_run = _run_details(api_base_url, api_token, run_id)
    source_workspace = _workspace_file_bytes(relative_workspace_path)
    source_checkpoints = _checkpoint_count(run_id)
    if (
        source_workspace is None
        or source_workspace.decode("utf-8").rstrip("\r\n") != expected_workspace_content
        or source_checkpoints <= 0
    ):
        raise RuntimeError("The source project is missing its representative workspace file or checkpoint")

    backup_path = backup_path.expanduser().resolve()
    create_backup(backup_path)
    manifest = verify_backup(backup_path)
    required_payloads = {"postgres.dump", "checkpoint/aura_checkpoints.db", "workspace.tar.gz"}
    if manifest.get("format_version") != 2 or not required_payloads <= set(manifest.get("files", {})):
        raise RuntimeError("The verified archive does not contain all three Kuractus data stores")

    recreated = False
    restored = False
    try:
        recreated = True
        _compose("down", "--volumes", "--remove-orphans")
        _compose("up", "-d", "--no-build")
        _wait_ready(api_base_url)

        fresh_status, _ = _api_request(api_base_url, f"/v1/runs/{run_id}", api_token)
        if fresh_status != 404:
            raise RuntimeError("The new Compose volumes were not empty before restore")
        if _checkpoint_count(run_id) != 0 or _workspace_file_bytes(relative_workspace_path) is not None:
            raise RuntimeError("The clean Compose volumes contain stale checkpoint or workspace data")

        restore_backup(backup_path, replace_current_data=True)
        restored = True
        _wait_ready(api_base_url)
        restored_run = _run_details(api_base_url, api_token, run_id)
        restored_checkpoints = _checkpoint_count(run_id)
        restored_workspace = _workspace_file_bytes(relative_workspace_path)
        if restored_workspace != source_workspace or restored_checkpoints <= 0:
            raise RuntimeError("The restored project is missing its representative workspace file or checkpoint")
    except BaseException:
        if recreated and not restored:
            try:
                _compose("up", "-d", "--no-build")
                _wait_ready(api_base_url)
                restore_backup(backup_path, replace_current_data=True)
                _wait_ready(api_base_url)
            except Exception:
                pass
        raise

    report = {
        "schema_version": 1,
        "scenario": "A6_clean_compose_backup_restore",
        "outcome": "PASS",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "execution": {
            "mode": "docker_compose_fresh_volumes",
            "live_inference_claim": False,
            "model_provider": model_provider,
            "external_provider_invocations": 0,
            "compose_project": project_name,
        },
        "source_commit_sha": _git_revision(),
        "run_id": run_id,
        "backup": {
            "format_version": manifest["format_version"],
            "created_at": manifest.get("created_at"),
            "archive_sha256": _archive_sha256(backup_path),
            "archive_size_bytes": backup_path.stat().st_size,
            "verified_payloads": sorted(manifest["files"]),
        },
        "stores": {
            "postgresql_run_record": {
                "source_status": source_run["status"],
                "absent_from_fresh_target_before_restore": True,
                "restored_status": restored_run["status"],
            },
            "langgraph_checkpoint": {
                "source_rows_for_run": source_checkpoints,
                "absent_from_fresh_target_before_restore": True,
                "restored_rows_for_run": restored_checkpoints,
            },
            "workspace_file": {
                "path": relative_workspace_path.as_posix(),
                "content_matches_expected_before_backup": True,
                "absent_from_fresh_target_before_restore": True,
                "restored_bytes_match_source": True,
                "sha256": hashlib.sha256(source_workspace).hexdigest(),
            },
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="New backup archive path outside the Compose volumes")
    parser.add_argument("run_id", help="Completed representative run already present in the Compose project")
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--api-token", default=os.environ.get("AURA_API_TOKEN", ""))
    parser.add_argument("--workspace-path", default="aura-compose-smoke.txt")
    parser.add_argument("--expected-workspace-content", default="persistent test")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.api_token:
        print("A6 ACCEPTANCE RESULT: FAIL (missing API token)", file=sys.stderr)
        return 1
    try:
        report = run_acceptance(
            backup_path=args.backup,
            report_path=args.report,
            api_base_url=args.api_base_url,
            api_token=args.api_token,
            run_id=args.run_id,
            workspace_path=args.workspace_path,
            expected_workspace_content=args.expected_workspace_content,
        )
    except Exception as exc:
        print(f"A6 ACCEPTANCE RESULT: FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"A6 ACCEPTANCE RESULT: PASS (run_id={report['run_id']}, report={args.report})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
