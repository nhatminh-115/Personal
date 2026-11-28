"""Exercise Automation webhook recovery across an API process restart.

The isolated local API uses Kuractus's deterministic mock model. A webhook body
contains an untrusted instruction, while the saved Automation instruction
requests a harmless workspace write. The run must pause for approval, survive
an API restart, and complete only after the persisted approval is granted.

The report records synthetic IDs, safe routing metadata, event types, and
assertions. It never stores the webhook body, saved instruction, approval
arguments, file contents, credentials, or model response.
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
import sqlite3
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4, uuid5, NAMESPACE_URL

import httpx
from sqlalchemy.engine import URL


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAVED_INSTRUCTION = "Write AURA_A4_APPROVED_MARKER to a4-approval-marker.txt"
CALLER_SENTINEL = "AURA_A4_UNTRUSTED_WEBHOOK_INSTRUCTION"
MARKER_PATH = "a4-approval-marker.txt"
MARKER_CONTENT = "AURA_A4_APPROVED_MARKER"
RUN_EVENT_TYPES = {
    "automation_triggered",
    "routing_profile_resolved",
    "model_selected",
    "approval_requested",
    "approval_granted",
    "tool_completed",
    "run_completed",
}


class AcceptanceFailure(RuntimeError):
    """An acceptance failure with a stable stage and safe category."""

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


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _runtime_environment(state_dir: Path, api_token: str) -> tuple[dict[str, str], Path, Path, Path]:
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
            "AURA_API_TOKEN": api_token,
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
    return environment, database_path, checkpoint_path, workspace_root


def _start_api(state_dir: Path, api_token: str) -> tuple[subprocess.Popen, str]:
    environment, _database_path, _checkpoint_path, _workspace_root = _runtime_environment(state_dir, api_token)
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
    return process, f"http://127.0.0.1:{port}"


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


async def _wait_until_ready(base_url: str, api_token: str, process: subprocess.Popen) -> None:
    headers = {"Authorization": f"Bearer {api_token}"}
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
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    return {
        "base_commit_sha": revision,
        "runner_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
    }


def _db_rows(database_path: Path, query: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    try:
        with sqlite3.connect(database_path, timeout=5) as connection:
            return list(connection.execute(query, params).fetchall())
    except (OSError, sqlite3.Error) as exc:
        raise AcceptanceFailure("persisted_state_inspection", "database_unavailable") from exc


def _safe_run_events(database_path: Path, run_id: str) -> list[dict[str, str]]:
    rows = _db_rows(
        database_path,
        "SELECT id, event_type FROM run_events WHERE run_id = ? ORDER BY created_at, id",
        (run_id,),
    )
    return [
        {"event_id": str(event_id), "event_type": str(event_type)}
        for event_id, event_type in rows
        if event_type in RUN_EVENT_TYPES
    ]


def _route_metadata(routing_response: dict[str, Any], run_id: str) -> dict[str, Any]:
    decisions = routing_response.get("decisions")
    if not isinstance(decisions, list):
        raise AcceptanceFailure("routing_inspection", "missing_persisted_routing")
    decision = next((item for item in decisions if isinstance(item, dict) and item.get("run_id") == run_id), None)
    if decision is None:
        raise AcceptanceFailure("routing_inspection", "missing_root_routing_decision")
    snapshot = decision.get("snapshot") if isinstance(decision.get("snapshot"), dict) else {}
    selection = decision.get("model_selection") if isinstance(decision.get("model_selection"), dict) else {}
    return {
        "provider": selection.get("provider"),
        "model": selection.get("model"),
        "profile_id": snapshot.get("profile_id"),
        "profile_version": snapshot.get("profile_version"),
        "winning_scope": snapshot.get("winning_scope"),
        "privacy_policy": snapshot.get("privacy_policy"),
        "fallback_policy": snapshot.get("fallback_policy"),
    }


async def _wait_for_status(
    client: httpx.AsyncClient,
    api_token: str,
    automation_id: str,
    event_id: str,
    expected_status: str,
    *,
    timeout_seconds: float = 45,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_token}"}
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = await client.get(f"/v1/automations/{automation_id}/runs", headers=headers)
        records = _expect(response, 200, "automation_history")
        record = next((item for item in records if item.get("event_id") == event_id), None)
        if record is not None and record.get("status") == expected_status:
            return record
        if record is not None and record.get("status") in {"failed", "cancelled", "dead_letter"}:
            raise AcceptanceFailure("automation_execution", f"run_{record['status']}")
        await asyncio.sleep(0.25)
    raise AcceptanceFailure("automation_execution", f"status_{expected_status}_timeout")


async def _exercise_queued_cancellation(
    client: httpx.AsyncClient,
    api_token: str,
) -> dict[str, str]:
    """Cancel a harmless manual run while it is queued or being cooperatively stopped."""
    headers = {"Authorization": f"Bearer {api_token}"}
    created_response = await client.post(
        "/v1/automations",
        headers=headers,
        json={
            "name": "A4 cancellation acceptance",
            "instruction": "Summarize the safe A4 cancellation test.",
            "scope": "global",
            "interval_seconds": 3600,
            "webhook_enabled": False,
        },
    )
    automation = _expect(created_response, 201, "cancellation_automation_create")
    automation_id = automation.get("id")
    _need(isinstance(automation_id, str) and bool(automation_id), "cancellation_automation_create")

    for _attempt in range(10):
        queued_response = await client.post(f"/v1/automations/{automation_id}/run", headers=headers)
        if queued_response.status_code == 409:
            await asyncio.sleep(0.1)
            continue
        queued = _expect(queued_response, 202, "cancellation_run_queue")
        event_id = queued.get("event_id")
        _need(isinstance(event_id, str) and bool(event_id), "cancellation_run_queue")
        run_id = str(uuid5(NAMESPACE_URL, f"aura-event-run:{event_id}"))

        cancel_response = await client.post(
            f"/v1/automations/{automation_id}/runs/{event_id}/cancel",
            headers=headers,
        )
        if cancel_response.status_code == 200:
            cancellation = _expect(cancel_response, 200, "cancellation_decision")
            for _poll in range(40):
                history_response = await client.get(f"/v1/automations/{automation_id}/runs", headers=headers)
                history = _expect(history_response, 200, "cancellation_history")
                current = next((item for item in history if item.get("event_id") == event_id), None)
                if current is not None and current.get("status") == "cancelled":
                    return {
                        "automation_id": automation_id,
                        "event_id": event_id,
                        "run_id": run_id,
                        "status": "cancelled",
                        "request_status": str(cancellation.get("status", "unknown")),
                    }
                if current is not None and current.get("status") in {"completed", "failed", "dead_letter"}:
                    break
                await asyncio.sleep(0.1)
        elif cancel_response.status_code != 409:
            raise AcceptanceFailure("cancellation_decision", f"http_{cancel_response.status_code}")

        # If the worker won the race and completed this harmless run first, try
        # again. The bounded loop gives the outbox's idle poll window a chance
        # to expose the queued-cancellation path without pausing production code.
        for _poll in range(40):
            history_response = await client.get(f"/v1/automations/{automation_id}/runs", headers=headers)
            history = _expect(history_response, 200, "cancellation_history")
            current = next((item for item in history if item.get("event_id") == event_id), None)
            if current is not None and current.get("status") in {"completed", "failed", "dead_letter", "cancelled"}:
                break
            await asyncio.sleep(0.1)

    raise AcceptanceFailure("queued_run_cancellation", "no_cancellable_dispatch_window")


async def run_acceptance(
    *,
    state_dir: Path | None = None,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the isolated webhook, approval, restart, and recovery scenario."""
    execution_id = uuid4().hex[:12]
    selected_state_dir = (state_dir or (REPOSITORY_ROOT / ".aura_dogfood" / "a4-automation-recovery" / execution_id)).resolve()
    selected_report_dir = (report_dir or (REPOSITORY_ROOT / "artifacts" / "dogfood")).resolve()
    selected_report_dir.mkdir(parents=True, exist_ok=True)
    report_name = f"a4-automation-recovery-{execution_id}.json"
    api_token = secrets.token_urlsafe(32)
    external_event_id = f"a4-{execution_id}"
    started_at = _utc_now()
    report: dict[str, Any] = {
        "schema_version": 1,
        "scenario": "A4_automation_recovery",
        "outcome": "FAIL",
        "started_at": started_at,
        "completed_at": None,
        "report_file": report_name,
        "source": _source_metadata(),
        "execution": {
            "mode": "isolated_local_api_processes",
            "model_provider": "mock",
            "live_inference_claim": False,
            "service_restart_count": 0,
        },
        "entities": {},
        "route": {},
        "events": [],
        "assertions": [],
    }
    process: subprocess.Popen | None = None
    failure_stage: str | None = None
    failure_category: str | None = None
    database_path = (selected_state_dir / "workspace.db").resolve()
    checkpoint_path = (selected_state_dir / "checkpoints.db").resolve()
    workspace_root = (selected_state_dir / "workspace").resolve()

    try:
        process, base_url = _start_api(selected_state_dir, api_token)
        await _wait_until_ready(base_url, api_token, process)
        auth_headers = {"Authorization": f"Bearer {api_token}"}

        async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
            created_response = await client.post(
                "/v1/automations",
                headers=auth_headers,
                json={
                    "name": "A4 recovery acceptance",
                    "instruction": SAVED_INSTRUCTION,
                    "scope": "global",
                    "interval_seconds": 3600,
                    "webhook_enabled": True,
                },
            )
            automation = _expect(created_response, 201, "automation_create")
            automation_id = automation.get("id")
            webhook_secret = automation.get("webhook_secret")
            webhook_path = automation.get("webhook_path")
            _need(isinstance(automation_id, str) and bool(automation_id), "automation_create")
            _need(isinstance(webhook_secret, str) and bool(webhook_secret), "webhook_secret_creation")
            _need(isinstance(webhook_path, str) and bool(webhook_path), "webhook_configuration")
            report["entities"]["automation_id"] = automation_id
            report["execution"]["webhook_secret_returned_at_creation"] = True
            _append_assertion(report, "webhook_secret_returned_once_at_creation")

            webhook_headers = {
                "Authorization": f"Bearer {webhook_secret}",
                "X-Aura-Event-Id": external_event_id,
            }
            webhook_response = await client.post(
                webhook_path,
                headers=webhook_headers,
                json={"instruction": CALLER_SENTINEL},
            )
            first_delivery = _expect(webhook_response, 202, "webhook_first_delivery")
            event_id = first_delivery.get("event_id")
            _need(isinstance(event_id, str) and bool(event_id), "webhook_first_delivery")
            report["entities"]["event_id"] = event_id
            report["entities"]["external_event_id"] = external_event_id
            _append_assertion(report, "webhook_delivery_queued_with_traceable_event_id")

            duplicate_response = await client.post(
                webhook_path,
                headers=webhook_headers,
                json={"instruction": CALLER_SENTINEL},
            )
            duplicate = _expect(duplicate_response, 202, "webhook_duplicate_delivery")
            _need(duplicate.get("event_id") == event_id, "webhook_duplicate_delivery")
            _append_assertion(report, "duplicate_webhook_delivery_reuses_original_event")

            expected_run_id = str(uuid5(NAMESPACE_URL, f"aura-event-run:{event_id}"))
            report["entities"]["run_id"] = expected_run_id
            waiting_record = await _wait_for_status(
                client,
                api_token,
                automation_id,
                event_id,
                "waiting_for_approval",
            )
            _need(waiting_record.get("run_id") == expected_run_id, "automation_run_identity")
            report["entities"]["session_id"] = waiting_record.get("session_id")

            pending_response = await client.get("/v1/approvals/pending", headers=auth_headers)
            pending = _expect(pending_response, 200, "approval_list_before_restart")
            approval = next(
                (item for item in pending if isinstance(item, dict) and item.get("run_id") == expected_run_id),
                None,
            )
            _need(approval is not None, "approval_pause")
            approval_id = approval.get("id")
            tool_input = approval.get("tool_input") if isinstance(approval.get("tool_input"), dict) else {}
            _need(approval.get("tool_name") == "write_workspace_file", "approval_tool_identity")
            _need(tool_input.get("path") == MARKER_PATH, "saved_instruction_controls_write_path")
            _need(tool_input.get("content") == MARKER_CONTENT, "saved_instruction_controls_write_content")
            _need(not (workspace_root / MARKER_PATH).exists(), "write_blocked_before_approval")
            _need(isinstance(approval_id, str) and bool(approval_id), "approval_pause")
            report["entities"]["approval_id"] = approval_id
            _append_assertion(report, "consequential_workspace_write_waits_for_approval")

        _stop_api(process)
        process = None
        report["execution"]["service_restart_count"] = 1

        process, restarted_base_url = _start_api(selected_state_dir, api_token)
        await _wait_until_ready(restarted_base_url, api_token, process)
        async with httpx.AsyncClient(base_url=restarted_base_url, timeout=15) as client:
            auth_headers = {"Authorization": f"Bearer {api_token}"}
            pending_response = await client.get("/v1/approvals/pending", headers=auth_headers)
            pending = _expect(pending_response, 200, "approval_list_after_restart")
            resumed_approval = next(
                (item for item in pending if isinstance(item, dict) and item.get("id") == report["entities"]["approval_id"]),
                None,
            )
            _need(resumed_approval is not None, "approval_survives_restart")
            _need(resumed_approval.get("run_id") == expected_run_id, "approval_run_identity_after_restart")

            history_response = await client.get(
                f"/v1/automations/{report['entities']['automation_id']}/runs",
                headers=auth_headers,
            )
            history = _expect(history_response, 200, "history_after_restart")
            restored_record = next(
                (item for item in history if isinstance(item, dict) and item.get("event_id") == report["entities"]["event_id"]),
                None,
            )
            _need(restored_record is not None, "event_history_survives_restart")
            _need(restored_record.get("run_id") == expected_run_id, "event_run_identity_after_restart")
            _need(restored_record.get("status") == "waiting_for_approval", "approval_paused_run_survives_restart")
            _append_assertion(report, "approval_paused_run_and_history_survive_api_restart")

            routing_response = await client.get(f"/v1/runs/{expected_run_id}/routing", headers=auth_headers)
            routing = _expect(routing_response, 200, "routing_after_restart")
            report["route"] = _route_metadata(routing, expected_run_id)
            _need(report["route"].get("provider") == "mock", "local_mock_route_persisted")
            _need(report["route"].get("privacy_policy") == "local_only", "automation_local_only_policy_persisted")

            decision_response = await client.post(
                f"/v1/approvals/{report['entities']['approval_id']}/decision",
                headers=auth_headers,
                json={"decision": "approved", "decision_notes": "A4 acceptance verification"},
            )
            decision = _expect(decision_response, 200, "approval_resume_after_restart")
            _need(decision.get("approval_id") == report["entities"]["approval_id"], "approval_identity_after_restart")
            _need(decision.get("run_id") == expected_run_id, "run_identity_after_approval")
            _need(decision.get("status") == "approved", "approval_decision_persisted")
            completed_record = await _wait_for_status(
                client,
                api_token,
                report["entities"]["automation_id"],
                report["entities"]["event_id"],
                "completed",
            )
            _need(completed_record.get("run_id") == expected_run_id, "run_identity_after_completion")
            _append_assertion(report, "approved_run_resumes_and_completes_after_restart")

            cancellation = await _exercise_queued_cancellation(client, api_token)
            report["cancellation"] = cancellation
            _append_assertion(report, "queued_automation_run_can_be_cancelled_and_retained_in_history")

        _need((workspace_root / MARKER_PATH).is_file(), "approved_workspace_write_exists")
        _need((workspace_root / MARKER_PATH).read_text(encoding="utf-8") == MARKER_CONTENT, "approved_workspace_write_content")
        _append_assertion(report, "approved_write_is_present_in_isolated_workspace")

        _stop_api(process)
        process = None

        secret_rows = _db_rows(
            database_path,
            "SELECT metadata_json FROM scheduled_jobs WHERE id = ?",
            (report["entities"]["automation_id"],),
        )
        _need(len(secret_rows) == 1, "webhook_secret_storage")
        stored_metadata = json.loads(secret_rows[0][0])
        stored_secret_hash = stored_metadata.get("webhook_secret_hash")
        _need(stored_secret_hash == hashlib.sha256(webhook_secret.encode("utf-8")).hexdigest(), "webhook_secret_digest")
        _need(webhook_secret not in secret_rows[0][0], "webhook_secret_not_stored_in_plaintext")
        _append_assertion(report, "webhook_secret_is_persisted_as_digest_only")

        event_rows = _db_rows(
            database_path,
            "SELECT payload_json, idempotency_key, status FROM events WHERE id = ?",
            (report["entities"]["event_id"],),
        )
        _need(len(event_rows) == 1, "event_persistence")
        event_payload = json.loads(event_rows[0][0])
        _need(event_rows[0][1] == f"automation-webhook-{report['entities']['automation_id']}-{external_event_id}", "event_idempotency_key")
        _need(event_rows[0][2] == "processed", "event_processed_status")
        _need(event_payload.get("message") == SAVED_INSTRUCTION, "saved_instruction_is_event_source")
        _need(CALLER_SENTINEL not in event_rows[0][0], "webhook_body_not_persisted")
        _append_assertion(report, "webhook_body_is_ignored_and_not_persisted")

        duplicate_rows = _db_rows(
            database_path,
            "SELECT COUNT(*) FROM events WHERE idempotency_key = ?",
            (event_rows[0][1],),
        )
        _need(duplicate_rows[0][0] == 1, "single_event_for_duplicate_delivery")
        _append_assertion(report, "duplicate_delivery_creates_no_second_outbox_event")

        cancellation_event_rows = _db_rows(
            database_path,
            "SELECT status FROM events WHERE id = ?",
            (report["cancellation"]["event_id"],),
        )
        _need(len(cancellation_event_rows) == 1, "cancelled_event_persistence")
        _need(cancellation_event_rows[0][0] in {"cancelled", "processed"}, "cancelled_event_terminal_status")
        cancellation_run_rows = _db_rows(
            database_path,
            "SELECT status FROM runs WHERE id = ?",
            (report["cancellation"]["run_id"],),
        )
        if cancellation_event_rows[0][0] == "processed":
            _need(
                len(cancellation_run_rows) == 1 and cancellation_run_rows[0][0] == "cancelled",
                "cancelled_run_persistence",
            )
        else:
            _need(
                not cancellation_run_rows or cancellation_run_rows[0][0] == "cancelled",
                "queued_cancellation_run_state",
            )

        run_rows = _db_rows(
            database_path,
            "SELECT id, session_id, status, routing_snapshot_json FROM runs WHERE id = ?",
            (expected_run_id,),
        )
        _need(len(run_rows) == 1, "run_persistence")
        run_row = run_rows[0]
        _need(run_row[2] == "completed", "completed_run_persisted")
        _need(json.loads(run_row[3]).get("source_event_id") == report["entities"]["event_id"], "run_event_provenance")
        report["entities"]["session_id"] = run_row[1]
        report["events"] = _safe_run_events(database_path, expected_run_id)
        event_types = {event["event_type"] for event in report["events"]}
        _need({"automation_triggered", "routing_profile_resolved", "model_selected", "approval_requested", "run_completed"} <= event_types, "safe_run_trace")
        report["events"].append({"event_id": report["entities"]["event_id"], "event_type": "outbox_event_processed"})
        _append_assertion(report, "persisted_run_trace_and_event_identity_are_consistent")

        _need(checkpoint_path.is_file() and checkpoint_path.stat().st_size > 0, "durable_checkpoint_store")
        report["outcome"] = "PASS"
    except AcceptanceFailure as exc:
        failure_stage = exc.stage
        failure_category = exc.category
    except (OSError, httpx.HTTPError, sqlite3.Error) as exc:
        failure_stage = "acceptance_execution"
        failure_category = type(exc).__name__
    finally:
        _stop_api(process)
        report["completed_at"] = _utc_now()
        if failure_stage is not None:
            report["outcome"] = "FAIL"
            report["failure"] = {"stage": failure_stage, "category": failure_category}
        report_path = selected_report_dir / report_name
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return report


async def _main(output: Path | None = None) -> int:
    report = await run_acceptance()
    if output is not None:
        output_path = output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report["report_file"] = output_path.name
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ACCEPTANCE RESULT: {report['outcome']} - A4 automation recovery")
    print(f"Sanitized report: {output if output is not None else report['report_file']}")
    if report["outcome"] != "PASS":
        failure = report.get("failure", {})
        print(f"Failure stage: {failure.get('stage', 'unknown')} ({failure.get('category', 'unknown')})")
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Also write the sanitized report to this path.")
    arguments = parser.parse_args()
    raise SystemExit(asyncio.run(_main(arguments.output)))
