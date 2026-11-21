"""Exercise persisted everyday workspace flows across an API process restart.

The runner creates synthetic records in an explicitly allowlisted test Compose
project. It uses the mock provider and never sends model or provider requests.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


ALLOWED_PROJECTS = {"aura-ci", "aura-a8-dogfood"}


def validate_test_project(project_name: str) -> None:
    if project_name not in ALLOWED_PROJECTS:
        raise ValueError("A8 acceptance is limited to the named CI and local dogfood projects")


def validate_api_url(api_base_url: str) -> None:
    parsed = urllib.parse.urlparse(api_base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("A8 acceptance must use the local Compose API")


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
    result = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _request(
    api_base_url: str,
    api_token: str,
    method: str,
    path: str,
    body: dict | None = None,
) -> tuple[int, dict | list | None, dict[str, str]]:
    headers = {"Authorization": f"Bearer {api_token}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    url = urllib.parse.urljoin(api_base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            payload = json.loads(raw) if raw else None
            return response.status, payload if isinstance(payload, (dict, list)) else None, dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload if isinstance(payload, (dict, list)) else None, dict(exc.headers.items())


def _call(
    api_base_url: str,
    api_token: str,
    method: str,
    path: str,
    body: dict | None = None,
    *,
    expected_status: int = 200,
) -> tuple[dict | list | None, dict[str, str]]:
    status, payload, headers = _request(api_base_url, api_token, method, path, body)
    if status != expected_status:
        raise RuntimeError(f"A8 API request returned HTTP {status}; expected {expected_status}")
    return payload, headers


def _cursor_collection(
    api_base_url: str,
    api_token: str,
    path: str,
    *,
    page_size: int,
    minimum_count: int,
    expected_ids: set[str] | None = None,
) -> list[dict]:
    base_path, _, raw_query = path.partition("?")
    base_params = dict(urllib.parse.parse_qsl(raw_query, keep_blank_values=True))
    items: list[dict] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        params = {**base_params, "page_size": str(page_size)}
        if cursor:
            params["cursor"] = cursor
        query = urllib.parse.urlencode(params)
        page, headers = _call(api_base_url, api_token, "GET", f"{base_path}?{query}")
        if not isinstance(page, list):
            raise RuntimeError("A8 collection returned an invalid page")
        items.extend(page)
        found_ids = {item.get("id") for item in items}
        if len(items) >= minimum_count and (expected_ids is None or expected_ids <= found_ids):
            return items
        next_cursor = headers.get("X-Next-Cursor") or headers.get("x-next-cursor")
        if not next_cursor:
            break
        if next_cursor in seen_cursors:
            raise RuntimeError("A8 collection repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    if len(items) < minimum_count or (expected_ids is not None and not expected_ids <= {item.get("id") for item in items}):
        raise RuntimeError("A8 collection did not return all persisted records across pages")
    return items


def _assert_conflict(
    api_base_url: str,
    api_token: str,
    method: str,
    path: str,
    body: dict,
    current_revision: int,
) -> None:
    status, payload, _ = _request(api_base_url, api_token, method, path, body)
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if status != 409 or not isinstance(detail, dict) or detail.get("current_revision") != current_revision:
        raise RuntimeError("A8 stale edit did not return the current revision conflict")


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
    raise RuntimeError("A8 Compose API did not become ready after restart")


def _model_provider() -> str:
    query = "from app.core.settings import settings; print(settings.MODEL_PROVIDER)"
    return _compose("exec", "-T", "aura-app", "python", "-c", query).strip()


def run_acceptance(api_base_url: str, api_token: str, report_path: Path) -> dict:
    project_name = os.environ.get("COMPOSE_PROJECT_NAME", "")
    validate_test_project(project_name)
    validate_api_url(api_base_url)
    started_at = _utc_now()
    if _model_provider() != "mock":
        raise RuntimeError("A8 acceptance requires the deterministic mock model provider")

    nonce = uuid.uuid4().hex[:10]
    workspace_project_name = f"A8 Dogfood {nonce}"
    marker = f"a8-workspace-marker-{nonce}"
    assertions: set[str] = set()

    project, _ = _call(
        api_base_url,
        api_token,
        "POST",
        "/v1/workspace/projects",
        {"name": workspace_project_name, "subtitle": "Everyday workspace continuity"},
        expected_status=201,
    )
    assert isinstance(project, dict)
    project_id = project["id"]

    notes = []
    for index in range(3):
        note, _ = _call(
            api_base_url,
            api_token,
            "POST",
            "/v1/workspace/notes",
            {
                "title": f"A8 saved note {index + 1} {nonce}",
                "body": f"{marker} — saved note content {index + 1}",
                "tags": ["A8", nonce],
                "project_names": [workspace_project_name],
            },
            expected_status=201,
        )
        assert isinstance(note, dict)
        notes.append(note)
    note_ids = {item["id"] for item in notes}
    _cursor_collection(
        api_base_url, api_token, "/v1/workspace/notes", page_size=2,
        minimum_count=len(note_ids), expected_ids=note_ids,
    )
    assertions.add("notes_pagination")

    library_references = []
    library_specs = [
        ("Study", "PDF", f"External file reference {marker}"),
        ("Reference", "HTML", f"External page reference {marker}"),
    ]
    for index, (collection, kind, detail) in enumerate(library_specs):
        reference, _ = _call(
            api_base_url,
            api_token,
            "POST",
            "/v1/workspace/library",
            {
                "name": f"A8 reference {index + 1} {nonce}",
                "kind": kind,
                "collection": collection,
                "detail": detail,
                "tags": ["A8", nonce],
                "project_names": [workspace_project_name],
            },
            expected_status=201,
        )
        assert isinstance(reference, dict)
        library_references.append(reference)
    library_ids = {item["id"] for item in library_references}
    _cursor_collection(
        api_base_url,
        api_token,
        f"/v1/workspace/library?{urllib.parse.urlencode({'q': nonce})}",
        page_size=1,
        minimum_count=2,
        expected_ids=library_ids,
    )
    assertions.add("library_search_and_pagination")

    study_material = library_references[0]
    session, _ = _call(
        api_base_url,
        api_token,
        "POST",
        "/v1/study/sessions",
        {
            "track_id": f"a8-track-{nonce}",
            "track_title": f"A8 study continuity {nonce}",
            "material_id": study_material["id"],
            "material_project_name": workspace_project_name,
        },
        expected_status=201,
    )
    assert isinstance(session, dict)
    cards = []
    for index in range(2):
        card, _ = _call(
            api_base_url,
            api_token,
            "POST",
            f"/v1/study/sessions/{session['id']}/cards",
            {"question": f"A8 question {index + 1} {nonce}", "answer": f"A8 answer {index + 1}"},
            expected_status=201,
        )
        assert isinstance(card, dict)
        cards.append(card)
    reviewed_card, _ = _call(
        api_base_url,
        api_token,
        "POST",
        f"/v1/study/sessions/{session['id']}/cards/{cards[0]['id']}/review",
        {"rating": "remembered", "expected_revision": cards[0]["revision"]},
    )
    assert isinstance(reviewed_card, dict) and reviewed_card["review_count"] == 1
    _assert_conflict(
        api_base_url,
        api_token,
        "PUT",
        f"/v1/study/sessions/{session['id']}/cards/{cards[0]['id']}",
        {"question": cards[0]["question"], "answer": cards[0]["answer"], "expected_revision": cards[0]["revision"]},
        reviewed_card["revision"],
    )
    study_card_ids = {item["id"] for item in cards}
    _cursor_collection(
        api_base_url, api_token, "/v1/study/cards", page_size=1,
        minimum_count=len(study_card_ids), expected_ids=study_card_ids,
    )
    assertions.update({"study_review_persistence", "study_revision_conflict", "study_pagination"})

    automations = []
    for index in range(2):
        automation, _ = _call(
            api_base_url,
            api_token,
            "POST",
            "/v1/automations",
            {
                "name": f"A8 automation {index + 1} {nonce}",
                "description": "A8 persistence acceptance",
                "instruction": "Record the scheduled workspace review state.",
                "scope": "project",
                "project_name": workspace_project_name,
                "interval_seconds": 3600,
                "webhook_enabled": False,
                "schedule": {"mode": "interval", "timezone": "UTC", "weekdays": []},
            },
            expected_status=201,
        )
        assert isinstance(automation, dict)
        automations.append(automation)
    updated_automation, _ = _call(
        api_base_url,
        api_token,
        "PATCH",
        f"/v1/automations/{automations[0]['id']}",
        {
            "name": f"A8 automation updated {nonce}",
            "description": "A8 persistence acceptance",
            "instruction": "Record the scheduled workspace review state.",
            "interval_seconds": 3600,
            "expected_revision": automations[0]["revision"],
        },
    )
    assert isinstance(updated_automation, dict)
    _assert_conflict(
        api_base_url,
        api_token,
        "PATCH",
        f"/v1/automations/{automations[0]['id']}",
        {
            "name": automations[0]["name"],
            "description": automations[0]["description"],
            "instruction": automations[0]["instruction"],
            "interval_seconds": automations[0]["interval_seconds"],
            "expected_revision": automations[0]["revision"],
        },
        updated_automation["revision"],
    )
    automation_ids = {item["id"] for item in automations}
    _cursor_collection(
        api_base_url, api_token, "/v1/automations", page_size=1,
        minimum_count=len(automation_ids), expected_ids=automation_ids,
    )
    assertions.update({"automation_revision_conflict", "automation_pagination"})

    note_update_body = {
        "title": f"A8 updated note {nonce}",
        "body": f"{marker} — reconciled after a concurrent edit",
        "tags": ["A8", nonce],
        "project_names": [workspace_project_name],
        "expected_revision": notes[0]["revision"],
    }
    updated_note, _ = _call(
        api_base_url,
        api_token,
        "PUT",
        f"/v1/workspace/notes/{notes[0]['id']}",
        note_update_body,
    )
    assert isinstance(updated_note, dict)
    stale_note_body = {**note_update_body, "title": notes[0]["title"], "expected_revision": notes[0]["revision"]}
    _assert_conflict(
        api_base_url,
        api_token,
        "PUT",
        f"/v1/workspace/notes/{notes[0]['id']}",
        stale_note_body,
        updated_note["revision"],
    )
    updated_library, _ = _call(api_base_url, api_token, "PUT", f"/v1/workspace/library/{study_material['id']}", {
        "name": f"A8 updated reference {nonce}",
        "kind": study_material["kind"],
        "collection": study_material["collection"],
        "detail": study_material["detail"],
        "tags": study_material["tags"],
        "project_names": study_material["project_names"],
        "expected_revision": study_material["revision"],
    })
    assert isinstance(updated_library, dict)
    _assert_conflict(
        api_base_url,
        api_token,
        "PUT",
        f"/v1/workspace/library/{study_material['id']}",
        {
            "name": study_material["name"],
            "kind": study_material["kind"],
            "collection": study_material["collection"],
            "detail": study_material["detail"],
            "tags": study_material["tags"],
            "project_names": study_material["project_names"],
            "expected_revision": study_material["revision"],
        },
        updated_library["revision"],
    )

    layout_path = f"/v1/workspace/projects/{urllib.parse.quote(workspace_project_name, safe='')}/layout"
    saved_layout, _ = _call(
        api_base_url,
        api_token,
        "PUT",
        layout_path,
        {"layout": {"positions": {notes[0]["id"]: {"x": 24, "y": 48}}}, "expected_revision": 0},
    )
    if not isinstance(saved_layout, dict) or saved_layout["revision"] != 1:
        raise RuntimeError("A8 project layout did not save")
    _assert_conflict(
        api_base_url,
        api_token,
        "PUT",
        layout_path,
        {"layout": {"positions": {}}, "expected_revision": 0},
        saved_layout["revision"],
    )

    project, _ = _call(
        api_base_url,
        api_token,
        "POST",
        f"/v1/workspace/projects/{project_id}/archive",
        {"expected_revision": project["revision"]},
    )
    assert isinstance(project, dict) and project["archived_at"] is not None
    project, _ = _call(
        api_base_url,
        api_token,
        "POST",
        f"/v1/workspace/projects/{project_id}/restore",
        {"expected_revision": project["revision"]},
    )
    assert isinstance(project, dict) and project["archived_at"] is None
    assertions.update({
        "note_revision_conflict",
        "library_revision_conflict",
        "automation_revision_conflict",
        "project_layout_revision_conflict",
        "project_layout_and_archive_restore",
    })

    search_query = urllib.parse.urlencode({"query": marker, "project_name": workspace_project_name, "limit": 20})
    search_results, _ = _call(api_base_url, api_token, "GET", f"/v1/workspace/search?{search_query}")
    if not isinstance(search_results, list) or notes[0]["id"] not in {item["object_id"] for item in search_results}:
        raise RuntimeError("A8 workspace search did not find the saved Note")
    assertions.add("workspace_search")

    completed_session, _ = _call(
        api_base_url, api_token, "POST", f"/v1/study/sessions/{session['id']}/complete",
    )
    if not isinstance(completed_session, dict) or completed_session.get("status") != "completed":
        raise RuntimeError("A8 Study session did not complete cleanly")
    session = completed_session

    _compose("restart", "aura-app")
    _wait_ready(api_base_url)
    if _model_provider() != "mock":
        raise RuntimeError("A8 model provider changed during restart")

    project_after = _cursor_collection(
        api_base_url, api_token, "/v1/workspace/projects", page_size=2,
        minimum_count=1, expected_ids={project_id},
    )
    persisted_project = next(item for item in project_after if item["id"] == project_id)
    if persisted_project["archived_at"] is not None:
        raise RuntimeError("A8 restored project did not survive the API restart")
    note_after, _ = _call(api_base_url, api_token, "GET", f"/v1/workspace/notes/{notes[0]['id']}")
    if not isinstance(note_after, dict) or note_after["revision"] != updated_note["revision"]:
        raise RuntimeError("A8 Note did not survive the API restart")
    _cursor_collection(
        api_base_url, api_token, "/v1/workspace/notes", page_size=2,
        minimum_count=len(note_ids), expected_ids=note_ids,
    )
    library_after = _cursor_collection(
        api_base_url,
        api_token,
        f"/v1/workspace/library?{urllib.parse.urlencode({'q': nonce})}",
        page_size=1,
        minimum_count=2,
        expected_ids=library_ids,
    )
    persisted_library = next(item for item in library_after if item["id"] == study_material["id"])
    if persisted_library["revision"] != updated_library["revision"]:
        raise RuntimeError("A8 Library update did not survive the API restart")
    study_sessions, _ = _call(api_base_url, api_token, "GET", "/v1/study/sessions?page_size=50")
    persisted_session = (
        next((item for item in study_sessions if item["id"] == session["id"]), None)
        if isinstance(study_sessions, list)
        else None
    )
    if persisted_session is None or persisted_session["status"] != "completed":
        raise RuntimeError("A8 Study session did not survive the API restart")
    study_cards = _cursor_collection(
        api_base_url, api_token, "/v1/study/cards", page_size=1,
        minimum_count=len(study_card_ids), expected_ids=study_card_ids,
    )
    persisted_review = next((item for item in study_cards if item["id"] == cards[0]["id"]), None)
    if persisted_review is None or persisted_review["review_count"] != 1:
        raise RuntimeError("A8 Study review state did not survive the API restart")
    automation_after = _cursor_collection(
        api_base_url, api_token, "/v1/automations", page_size=1,
        minimum_count=len(automation_ids), expected_ids=automation_ids,
    )
    persisted_automation = next((item for item in automation_after if item["id"] == automations[0]["id"]), None)
    if persisted_automation is None or persisted_automation["revision"] != updated_automation["revision"]:
        raise RuntimeError("A8 Automation configuration did not survive the API restart")
    layout_after, _ = _call(api_base_url, api_token, "GET", layout_path)
    if not isinstance(layout_after, dict) or layout_after["layout"] != saved_layout["layout"]:
        raise RuntimeError("A8 project layout did not survive the API restart")
    graph_query = urllib.parse.urlencode({"include_project_state": "false"})
    graph, _ = _call(
        api_base_url,
        api_token,
        "GET",
        f"/v1/workspace/projects/{urllib.parse.quote(workspace_project_name, safe='')}/graph?{graph_query}",
    )
    if not isinstance(graph, dict):
        raise RuntimeError("A8 project graph could not be reopened after restart")
    graph_object_ids = {item["id"] for item in graph.get("objects", [])}
    expected_graph_ids = {notes[0]["id"], study_material["id"], session["id"], *[card["id"] for card in cards]}
    if not expected_graph_ids <= graph_object_ids:
        raise RuntimeError("A8 project graph lost linked Note, Library, or Study objects after restart")
    search_after, _ = _call(api_base_url, api_token, "GET", f"/v1/workspace/search?{search_query}")
    if not isinstance(search_after, list) or notes[0]["id"] not in {item["object_id"] for item in search_after}:
        raise RuntimeError("A8 workspace search did not recover after restart")
    assertions.update({
        "project_persistence_after_restart",
        "notes_persistence_after_restart",
        "library_persistence_after_restart",
        "study_persistence_after_restart",
        "automation_persistence_after_restart",
        "layout_persistence_after_restart",
        "project_graph_link_persistence_after_restart",
        "search_recovery_after_restart",
    })

    report = {
        "schema_version": 1,
        "scenario": "A8_everyday_workspace_continuity",
        "outcome": "PASS",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "execution": {
            "mode": "docker_compose_api_restart",
            "compose_project": project_name,
            "model_provider": "mock",
            "live_inference_claim": False,
            "external_provider_invocations": 0,
        },
        "source_commit_sha": _git_revision(),
        "workspace_project_id": project_id,
        "note_ids": [item["id"] for item in notes],
        "library_reference_ids": [item["id"] for item in library_references],
        "study_session_id": session["id"],
        "study_card_ids": [item["id"] for item in cards],
        "automation_ids": [item["id"] for item in automations],
        "assertions": [{"name": name, "result": "PASS"} for name in sorted(assertions)],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--api-token", default=os.environ.get("AURA_API_TOKEN", ""))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if not args.api_token:
        print("A8 ACCEPTANCE RESULT: FAIL (missing API token)", file=sys.stderr)
        return 1
    try:
        report = run_acceptance(args.api_base_url, args.api_token, args.report)
    except Exception as exc:
        print(f"A8 ACCEPTANCE RESULT: FAIL ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"A8 ACCEPTANCE RESULT: PASS (project_id={report['workspace_project_id']}, report={args.report})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
