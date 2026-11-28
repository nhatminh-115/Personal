"""Exercise Kuractus project continuity through a real API process restart.

The scenario uses the deterministic mock model because A1 proves workspace,
session, and context durability rather than live-provider quality. It starts an
isolated Uvicorn process, creates a project and linked Notes, sends a chat with
explicit context, stops the process, then reopens the same workspace through a
new process and verifies persisted scope and provenance.

Reports contain synthetic object/run/event IDs and sanitized route metadata.
They never contain note bodies, prompts, responses, credentials, or raw events.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy.engine import URL


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEVANT_EVENT_TYPES = {
    "routing_profile_resolved",
    "model_selected",
    "context_compiled",
    "run_completed",
}


class AcceptanceFailure(RuntimeError):
    """A sanitized failure with a stable scenario stage and category."""

    def __init__(self, stage: str, category: str) -> None:
        super().__init__(category)
        self.stage = stage
        self.category = category


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _need(condition: bool, stage: str) -> None:
    if not condition:
        raise AcceptanceFailure(stage, "assertion_failed")


def _expect(response: httpx.Response, status_code: int, stage: str) -> Any:
    if response.status_code != status_code:
        raise AcceptanceFailure(stage, f"http_{response.status_code}")
    try:
        return response.json() if response.content else None
    except ValueError as exc:
        raise AcceptanceFailure(stage, "invalid_json_response") from exc


def _manifest_workspace_objects(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    legacy_objects = manifest.get("objects")
    if isinstance(legacy_objects, list):
        return [item for item in legacy_objects if isinstance(item, dict)]
    included = manifest.get("included_objects", [])
    if not isinstance(included, list):
        return []
    return [
        {
            "object_id": item.get("object_id"),
            "object_type": item.get("source_type"),
            "selected_by_user": item.get("selected_by_user") is True,
            "source_object_ids": item.get("source_object_ids", []),
        }
        for item in included
        if isinstance(item, dict)
    ]


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _runtime_environment(state_dir: Path) -> tuple[dict[str, str], Path, Path]:
    state_dir.mkdir(parents=True, exist_ok=True)
    database_path = (state_dir / "workspace.db").resolve()
    checkpoint_path = (state_dir / "checkpoints.db").resolve()
    workspace_root = (state_dir / "workspace").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    no_mcp_config = (state_dir / "mcp-servers.json").resolve()

    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_URL": URL.create(
                "sqlite+aiosqlite", database=str(database_path)
            ).render_as_string(hide_password=False),
            "CHECKPOINT_DB_PATH": str(checkpoint_path),
            "AURA_WORKSPACE_ROOT": str(workspace_root),
            "AURA_API_TOKEN": secrets.token_hex(24),
            "MODEL_PROVIDER": "mock",
            "EMBEDDING_PROVIDER": "mock",
            "OPENAI_API_KEY": "",
            "AURA_DOGFOOD_MODEL_OVERRIDE": "",
            "RESEARCH_PROVIDER_MODE": "deterministic",
            "OLLAMA_BASE_URL": "http://127.0.0.1:9/v1",
            "LMSTUDIO_BASE_URL": "http://127.0.0.1:9/v1",
            "MCP_CONFIG_PATH": str(no_mcp_config),
            "DATABASE_ECHO": "false",
            "PYTHONPATH": os.pathsep.join(
                part
                for part in (str(REPOSITORY_ROOT), environment.get("PYTHONPATH", ""))
                if part
            ),
        }
    )
    return environment, database_path, checkpoint_path


def _start_api(state_dir: Path) -> tuple[subprocess.Popen, str, dict[str, str]]:
    environment, _database_path, _checkpoint_path = _runtime_environment(state_dir)
    port = _available_port()
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.api.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-access-log",
        "--log-level",
        "warning",
    ]
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return process, f"http://127.0.0.1:{port}", environment


def _stop_api(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.send_signal(signal.SIGTERM)
        process.wait(timeout=12)
    except (OSError, subprocess.TimeoutExpired):
        process.kill()
        process.wait(timeout=5)


async def _wait_until_ready(base_url: str, token: str, process: subprocess.Popen) -> None:
    headers = {"Authorization": f"Bearer {token}"}
    deadline = time.monotonic() + 45
    async with httpx.AsyncClient(timeout=2) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AcceptanceFailure("service_start", "service_exited")
            try:
                response = await client.get(f"{base_url}/ready", headers=headers)
                if response.status_code == 200 and response.json().get("status") == "ready":
                    return
            except (httpx.HTTPError, ValueError):
                pass
            await asyncio.sleep(0.25)
    raise AcceptanceFailure("service_start", "readiness_timeout")


def _append_assertion(report: dict[str, Any], name: str) -> None:
    report["assertions"].append({"name": name, "result": "PASS"})


def _source_metadata() -> dict[str, str]:
    runner_path = Path(__file__).resolve()
    revision = os.environ.get("AURA_SOURCE_COMMIT_SHA", "").strip().lower()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        try:
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            revision = "unknown"
    return {
        "base_commit_sha": revision,
        "runner_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
    }


def _relevant_events(run_details: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"event_id": event["id"], "event_type": event["event_type"]}
        for event in run_details.get("events", [])
        if isinstance(event, dict)
        and isinstance(event.get("id"), str)
        and event.get("event_type") in RELEVANT_EVENT_TYPES
    ]


def _route_metadata(routing: dict[str, Any], run_id: str) -> dict[str, Any]:
    decision = next(
        (
            item
            for item in routing.get("decisions", [])
            if isinstance(item, dict) and item.get("run_id") == run_id
        ),
        {},
    )
    snapshot = decision.get("snapshot") if isinstance(decision.get("snapshot"), dict) else {}
    selection = decision.get("model_selection") if isinstance(decision.get("model_selection"), dict) else {}
    return {
        key: value
        for key, value in {
            "provider": selection.get("provider"),
            "model": selection.get("model"),
            "profile_id": snapshot.get("profile_id") or selection.get("profile_id"),
            "profile_version": snapshot.get("profile_version") or selection.get("profile_version"),
            "winning_scope": snapshot.get("winning_scope") or selection.get("winning_scope"),
            "privacy_policy": snapshot.get("privacy_policy") or selection.get("privacy"),
            "fallback_policy": snapshot.get("fallback_policy") or selection.get("fallback_policy"),
        }.items()
        if value is not None
    }


async def run_acceptance(
    *, state_dir: Path | None = None, report_dir: Path | None = None
) -> dict[str, Any]:
    """Run A1 against two fresh API processes sharing only isolated durable state."""
    run_key = uuid4().hex[:12]
    default_state = REPOSITORY_ROOT / ".aura_dogfood" / f"continuity-{run_key}"
    default_reports = REPOSITORY_ROOT / "artifacts" / "dogfood"
    state_root = (state_dir or default_state).resolve()
    output_root = (report_dir or default_reports).resolve()
    report_path = output_root / f"a1-project-continuity-{run_key}.json"
    project_name = f"a1-continuity-{run_key}"
    foreign_project_name = f"a1-foreign-{run_key}"
    session_id = str(uuid4())
    client_turn_id = f"a1-continuity-{run_key}"
    report: dict[str, Any] = {
        "schema_version": 1,
        "scenario": "A1_project_continuity",
        "outcome": "FAIL",
        "started_at": _utc_now(),
        "execution": {
            "mode": "isolated_local_api_processes",
            "model_provider": "mock",
            "live_inference_claim": False,
            "service_restart_count": 0,
        },
        "source": _source_metadata(),
        "entities": {
            "project_name": project_name,
            "foreign_project_name": foreign_project_name,
            "session_id": session_id,
        },
        "assertions": [],
        "events": [],
    }
    process: subprocess.Popen | None = None
    stage = "service_start"

    try:
        process, base_url, environment = _start_api(state_root)
        token = environment["AURA_API_TOKEN"]
        await _wait_until_ready(base_url, token, process)
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30) as client:
            stage = "project_create"
            project = _expect(
                await client.post(
                    "/v1/workspace/projects",
                    json={"name": project_name, "subtitle": "A1 continuity acceptance"},
                ),
                201,
                stage,
            )
            foreign_project = _expect(
                await client.post(
                    "/v1/workspace/projects",
                    json={"name": foreign_project_name, "subtitle": "A1 scope decoy"},
                ),
                201,
                "foreign_project_create",
            )
            _need(project.get("name") == project_name, stage)
            _need(foreign_project.get("name") == foreign_project_name, "foreign_project_create")
            _append_assertion(report, "project_created")

            stage = "note_create"
            note_body = f"Synthetic A1 continuity marker {run_key} belongs to the primary project."
            decoy_body = f"Synthetic foreign-project decoy {run_key} must stay out of selected context."
            user_message = "Use only the selected project note for this continuity check."
            note = _expect(
                await client.post(
                    "/v1/workspace/notes",
                    json={
                        "title": f"A1 continuity note {run_key}",
                        "body": note_body,
                        "project_names": [project_name],
                    },
                ),
                201,
                stage,
            )
            decoy = _expect(
                await client.post(
                    "/v1/workspace/notes",
                    json={
                        "title": f"A1 foreign decoy {run_key}",
                        "body": decoy_body,
                        "project_names": [foreign_project_name],
                    },
                ),
                201,
                "decoy_note_create",
            )
            note_id, decoy_note_id = note["id"], decoy["id"]
            report["entities"].update({"note_id": note_id, "foreign_note_id": decoy_note_id})
            _need(project_name in note.get("project_names", []), stage)
            _need(foreign_project_name in decoy.get("project_names", []), "decoy_note_create")
            _append_assertion(report, "note_linked_to_project")

            stage = "context_preview"
            preview = _expect(
                await client.post(
                    f"/v1/workspace/projects/{project_name}/context/preview",
                    json={"selected_object_ids": [note_id]},
                ),
                200,
                stage,
            )
            preview_objects = preview.get("objects", [])
            _need(
                len(preview_objects) == 1
                and preview_objects[0].get("object_id") == note_id
                and preview_objects[0].get("object_type") == "manual_note"
                and preview_objects[0].get("selected_by_user") is True,
                stage,
            )
            _need(note_body in preview.get("prompt_text", ""), stage)
            _need(decoy_body not in preview.get("prompt_text", ""), stage)
            report["context_preview"] = {
                "selected_object_ids": [note_id],
                "object_types": ["manual_note"],
                "foreign_note_excluded": True,
            }
            _append_assertion(report, "selected_context_preview_is_scoped")

            stage = "chat_start"
            chat = _expect(
                await client.post(
                    "/v1/chat",
                    json={
                        "session_id": session_id,
                        "client_turn_id": client_turn_id,
                        "message": user_message,
                        "project_name": project_name,
                        "context_object_ids": [note_id],
                    },
                ),
                200,
                stage,
            )
            run_id = chat.get("run_id")
            report["entities"]["run_id"] = run_id
            _need(
                chat.get("status") == "completed"
                and chat.get("session_id") == session_id
                and isinstance(run_id, str),
                stage,
            )
            _append_assertion(report, "chat_completed_in_project_session")

            stage = "initial_provenance"
            routing = _expect(await client.get(f"/v1/runs/{run_id}/routing"), 200, stage)
            decisions = routing.get("decisions", [])
            decision = next(
                (item for item in decisions if isinstance(item, dict) and item.get("run_id") == run_id),
                {},
            )
            manifest = decision.get("context_manifest") if isinstance(decision.get("context_manifest"), dict) else {}
            manifest_objects = _manifest_workspace_objects(manifest)
            _need(
                len(manifest_objects) == 1
                and manifest_objects[0].get("object_id") == note_id
                and manifest_objects[0].get("selected_by_user") is True,
                stage,
            )
            _need(decoy_note_id not in {item.get("object_id") for item in manifest_objects}, stage)
            _append_assertion(report, "chat_context_provenance_is_scoped")

        _stop_api(process)
        process = None
        report["execution"]["service_restart_count"] = 1

        stage = "service_restart"
        process, base_url, environment = _start_api(state_root)
        await _wait_until_ready(base_url, environment["AURA_API_TOKEN"], process)
        headers = {"Authorization": f"Bearer {environment['AURA_API_TOKEN']}"}
        async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30) as client:
            stage = "project_reopen"
            projects = _expect(await client.get("/v1/workspace/projects"), 200, stage)
            reopened_project = next(
                (item for item in projects if item.get("name") == project_name), None
            )
            _need(reopened_project is not None, stage)
            note_after_restart = _expect(
                await client.get(f"/v1/workspace/notes/{note_id}"), 200, "note_reopen"
            )
            _need(
                project_name in note_after_restart.get("project_names", [])
                and note_after_restart.get("title") == note.get("title")
                and note_after_restart.get("body") == note_body,
                "note_reopen",
            )
            summary = _expect(
                await client.get("/v1/workspace/summary", params={"project_name": project_name}),
                200,
                "project_summary_reopen",
            )
            _need(summary.get("project_note_count") == 1, "project_summary_reopen")
            graph = _expect(
                await client.get(
                    f"/v1/workspace/projects/{project_name}/graph",
                    params={"object_types": "manual_note"},
                ),
                200,
                "project_graph_reopen",
            )
            graph_ids = {item.get("id") for item in graph.get("objects", [])}
            _need(note_id in graph_ids and decoy_note_id not in graph_ids, "project_graph_reopen")
            report["reopened_workspace"] = {
                "project_found": True,
                "linked_note_found": True,
                "project_note_count": summary["project_note_count"],
                "foreign_note_excluded": True,
            }
            _append_assertion(report, "project_and_note_reopened_with_scope")

            stage = "session_reopen"
            session = _expect(await client.get(f"/v1/sessions/{session_id}"), 200, stage)
            messages = session.get("messages", [])
            _need(
                session.get("project_name") == project_name
                and len(messages) >= 2
                and {message.get("role") for message in messages} >= {"user", "assistant"}
                and any(message.get("run_id") == run_id for message in messages)
                and any(
                    message.get("role") == "user" and message.get("content") == user_message
                    for message in messages
                ),
                stage,
            )
            _append_assertion(report, "session_transcript_and_project_scope_reopened")

            stage = "run_reopen"
            run_details = _expect(await client.get(f"/v1/runs/{run_id}"), 200, stage)
            _need(run_details.get("status") == "completed", stage)
            routing_after_restart = _expect(
                await client.get(f"/v1/runs/{run_id}/routing"), 200, "routing_reopen"
            )
            reopened_decision = next(
                (
                    item
                    for item in routing_after_restart.get("decisions", [])
                    if isinstance(item, dict) and item.get("run_id") == run_id
                ),
                {},
            )
            reopened_manifest = (
                reopened_decision.get("context_manifest")
                if isinstance(reopened_decision.get("context_manifest"), dict)
                else {}
            )
            reopened_objects = _manifest_workspace_objects(reopened_manifest)
            _need(
                len(reopened_objects) == 1
                and reopened_objects[0].get("object_id") == note_id
                and reopened_objects[0].get("selected_by_user") is True,
                "routing_reopen",
            )
            _need(decoy_note_id not in {item.get("object_id") for item in reopened_objects}, "routing_reopen")
            report["route"] = _route_metadata(routing_after_restart, run_id)
            _need(report["route"].get("provider") == "mock", "route_metadata")
            report["events"] = _relevant_events(run_details)
            _need(
                {event["event_type"] for event in report["events"]}
                >= {"routing_profile_resolved", "model_selected", "context_compiled"},
                "persisted_events",
            )
            report["persisted_context"] = {
                "selected_object_ids": [note_id],
                "foreign_note_excluded": True,
            }
            _append_assertion(report, "run_and_context_provenance_survived_restart")

        report["outcome"] = "PASS"
        report["completed_at"] = _utc_now()
        report["report_file"] = report_path.name
        output_root.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return report
    except Exception as exc:
        report["outcome"] = "FAIL"
        report["failed_at"] = _utc_now()
        report["failure_stage"] = exc.stage if isinstance(exc, AcceptanceFailure) else stage
        report["failure_category"] = (
            exc.category if isinstance(exc, AcceptanceFailure) else type(exc).__name__
        )
        output_root.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if isinstance(exc, AcceptanceFailure):
            raise
        raise AcceptanceFailure(stage, type(exc).__name__) from None
    finally:
        _stop_api(process)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, help="Isolated database/checkpoint directory")
    parser.add_argument("--report-dir", type=Path, help="Sanitized acceptance report directory")
    args = parser.parse_args()
    try:
        report = asyncio.run(run_acceptance(state_dir=args.state_dir, report_dir=args.report_dir))
    except AcceptanceFailure as exc:
        print(f"ACCEPTANCE RESULT: FAIL (stage={exc.stage}, category={exc.category})")
        return 1
    print("ACCEPTANCE RESULT: PASS - project data, selected context, session, and provenance survived an API process restart.")
    print(f"RUN ID: {report['entities']['run_id']}")
    print(f"REPORT: {report['report_file']}")
    print("MODEL PROVIDER: mock (no live inference claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
