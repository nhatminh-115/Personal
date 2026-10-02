"""Live, read-only Coding Specialist dogfood for optional code-graph fallback.

Requires explicit OpenAI credentials and writes isolated SQLite/checkpoint files under
.aura_dogfood. It never installs optional providers or resolves approvals.
"""
import asyncio
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any, Mapping

CODING_IMPACT_WORKLOAD = (
    "Use the Coding Specialist to perform a read-only impact analysis of AURA's optional code-graph capability path. "
    "Determine how code_graph capabilities become available, how MCP discovery verifies tool bindings, and what the "
    "Coding Specialist does when no code-graph provider is configured. Read the relevant source and tests before "
    "concluding. Do not modify files, run write commands, install/download/configure a provider, or approve any action. "
    "If a code-graph tool is already available in this runtime you may use it; otherwise continue with native workspace "
    "and sandbox read tools. Return a concise impact report naming source files and existing tests, with evidence separated "
    "from recommendations."
)


def live_environment_error(environ: Mapping[str, str] | None = None) -> str | None:
    """Return a fail-fast explanation unless a real supported model is configured."""
    values = os.environ if environ is None else environ
    provider = values.get("MODEL_PROVIDER", "").strip().lower()
    if provider != "openai":
        return "Coding live dogfood requires MODEL_PROVIDER=openai; mock routing is not accepted."
    if not values.get("OPENAI_API_KEY", "").strip():
        return "Coding live dogfood requires OPENAI_API_KEY; no model call was made."
    return None


def _event_payload(event: Any) -> dict[str, Any]:
    payload = getattr(event, "payload", None)
    return payload if isinstance(payload, dict) else {}


def _model_decisions(events: list[Any]) -> list[dict[str, Any]]:
    fields = ("agent_role", "provider", "model", "profile_id", "profile_version", "winning_scope", "selection_reason")
    return [
        {key: payload[key] for key in fields if payload.get(key) is not None}
        for event in events
        if getattr(event, "event_type", None) == "model_selected"
        for payload in [_event_payload(event)]
    ]


def _pending_approval_ids(events: list[Any]) -> list[str]:
    return [
        str(payload["approval_id"])
        for event in events
        if getattr(event, "event_type", None) == "approval_requested"
        for payload in [_event_payload(event)]
        if payload.get("approval_id")
    ]


def _context_manifest(events: list[Any]) -> dict[str, Any] | None:
    event = next((item for item in events if getattr(item, "event_type", None) == "context_compiled"), None)
    if event is None:
        return None
    payload = _event_payload(event)
    keys = (
        "objects", "estimated_tokens", "character_count", "privacy_requirement", "privacy_sources",
        "required_capabilities", "required_tool_capabilities", "resolved_tool_names", "capability_requirements",
    )
    return {key: payload[key] for key in keys if key in payload}


def _safe_run_events(events: list[Any]) -> dict[str, Any]:
    tools: list[str] = []
    artifacts: list[str] = []
    failures: list[dict[str, Any]] = []
    for event in events:
        kind = getattr(event, "event_type", "")
        payload = _event_payload(event)
        tool = payload.get("tool") or payload.get("tool_name") or payload.get("name")
        if kind in {"tool_requested", "tool_executed", "tool_failed"} and isinstance(tool, str):
            if kind == "tool_executed":
                tools.append(tool)
                result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
                for key in ("path", "artifact_id", "object_id"):
                    value = metadata.get(key)
                    if isinstance(value, str) and value not in artifacts:
                        artifacts.append(value)
                if result.get("success") is False:
                    failures.append({"kind": "tool_execution", "tool": tool})
            elif kind == "tool_failed":
                failures.append({"kind": "tool_execution", "tool": tool})
        elif kind == "run_failed":
            failures.append({"kind": "run", "error_category": payload.get("error_category", "unknown")})
    return {"tool_sequence": tools, "artifacts": artifacts, "failures": failures}


def configure_isolated_runtime(workspace_root: Path, run_key: str) -> None:
    """Point all mutable runtime state at ignored, run-specific dogfood files."""
    from sqlalchemy.engine import URL

    isolated = Path(".aura_dogfood").resolve()
    isolated.mkdir(parents=True, exist_ok=True)
    database_path = isolated / f"coding-{run_key}.db"
    checkpoint_path = isolated / f"coding-{run_key}-checkpoints.db"
    os.environ["DATABASE_URL"] = URL.create(
        "sqlite+aiosqlite", database=str(database_path)
    ).render_as_string(hide_password=False)
    os.environ["CHECKPOINT_DB_PATH"] = str(checkpoint_path)
    os.environ["AURA_WORKSPACE_ROOT"] = str(workspace_root.resolve())

    from app.core.settings import settings
    settings.DATABASE_URL = os.environ["DATABASE_URL"]
    settings.CHECKPOINT_DB_PATH = checkpoint_path
    settings.AURA_WORKSPACE_ROOT = workspace_root.resolve()
    settings.MODEL_PROVIDER = "openai"

    from app.db import session as db_session
    db_session.configure_engine(settings.DATABASE_URL)


async def audit_coding_run(parent_run_id: str, response_status: str, elapsed_seconds: float) -> dict[str, Any]:
    """Summarize durable lineage without prompts, source text, or raw tool output."""
    from sqlalchemy import select
    from app.db.models import DelegationModel, RunEventModel, RunModel
    from app.db.session import async_session_factory
    from app.orchestrator.graph import get_compiled_graph

    async with async_session_factory() as db:
        parent = await db.get(RunModel, parent_run_id)
        if parent is None:
            raise ValueError(f"Persisted parent run {parent_run_id} was not found.")
        delegation_result = await db.execute(
            select(DelegationModel)
            .where(DelegationModel.parent_run_id == parent_run_id)
            .order_by(DelegationModel.created_at.asc(), DelegationModel.id.asc())
        )
        delegations = list(delegation_result.scalars())
        event_result = await db.execute(
            select(RunEventModel).where(RunEventModel.run_id == parent_run_id).order_by(RunEventModel.created_at.asc())
        )
        parent_events = list(event_result.scalars())
        children = []
        for delegation in delegations:
            child = await db.get(RunModel, delegation.child_run_id)
            if child is None:
                continue
            child_result = await db.execute(
                select(RunEventModel).where(RunEventModel.run_id == child.id).order_by(RunEventModel.created_at.asc())
            )
            child_events = list(child_result.scalars())
            children.append({
                "run_id": child.id,
                "specialist": delegation.specialist_name,
                "status": child.status,
                "routing_decisions": _model_decisions(child_events),
                "context_manifest": _context_manifest(child_events),
                "pending_approval_ids": _pending_approval_ids(child_events),
                **_safe_run_events(child_events),
            })

        graph = await get_compiled_graph()
        checkpoints: dict[str, Any] = {}
        for run_id in [parent_run_id, *(child["run_id"] for child in children)]:
            try:
                snapshot = await graph.aget_state({"configurable": {"thread_id": run_id}})
                checkpoints[run_id] = {
                    "present": snapshot is not None,
                    "awaiting_resume": bool(getattr(snapshot, "next", ())),
                }
            except Exception:
                checkpoints[run_id] = {"present": False, "awaiting_resume": False}

        report = {
            "scenario": "coding_impact_optional_code_graph",
            "parent_run_id": parent_run_id,
            "parent_status": parent.status,
            "response_status": response_status,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "routing_decisions": _model_decisions(parent_events),
            "context_manifest": _context_manifest(parent_events),
            "children": children,
            "checkpoint_status": checkpoints,
            "pending_approval_ids": _pending_approval_ids(parent_events),
        }
        all_decisions = report["routing_decisions"] + [
            decision for child in children for decision in child["routing_decisions"]
        ]
        report["pending_approval_ids"] = list(dict.fromkeys(
            report["pending_approval_ids"] + [approval_id for child in children for approval_id in child["pending_approval_ids"]]
        ))
        report["coding_specialist_delegated"] = any(item["specialist"] == "coding" for item in children)
        report["non_mock_model_used"] = any(decision.get("provider") not in (None, "mock") for decision in all_decisions)
        return report


async def run_live_dogfood() -> None:
    error = live_environment_error()
    if error:
        print(f"REAL CODING DOGFOOD NOT EXECUTED — {error}")
        raise SystemExit(2)

    run_key = uuid.uuid4().hex[:12]
    workspace_root = Path(os.environ.get("AURA_DOGFOOD_WORKSPACE_ROOT", Path.cwd())).resolve()
    if not workspace_root.is_dir():
        raise SystemExit(f"AURA_DOGFOOD_WORKSPACE_ROOT is not a directory: {workspace_root}")
    configure_isolated_runtime(workspace_root, run_key)

    import httpx
    from app.api.server import create_app, lifespan
    from app.core.settings import settings
    from app.orchestrator.graph import init_checkpointer

    await init_checkpointer(settings.CHECKPOINT_DB_PATH)
    app = create_app()
    session_id = f"sess-dogfood-coding-{run_key}"
    started = time.monotonic()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=300.0) as client:
            response = await client.post("/v1/chat", json={
                "session_id": session_id,
                "message": CODING_IMPACT_WORKLOAD,
            })
            if response.status_code != 200:
                raise SystemExit(f"/v1/chat failed with HTTP {response.status_code}; inspect the server log.")
            payload = response.json()
            parent_run_id = payload.get("run_id")
            response_status = payload.get("status", "unknown")
            if not isinstance(parent_run_id, str):
                raise SystemExit("/v1/chat returned no run_id; no durable run can be audited.")

    report = await audit_coding_run(parent_run_id, response_status, time.monotonic() - started)
    output_dir = Path("artifacts/dogfood").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"coding-impact-{parent_run_id}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Audit artifact: {report_path}")

    if report["pending_approval_ids"]:
        print("Run is paused for human approval. No decision was submitted by this dogfood script.")
        raise SystemExit(2)
    if not report["coding_specialist_delegated"]:
        raise SystemExit("Acceptance failed: root did not delegate to the Coding Specialist.")
    if not report["non_mock_model_used"]:
        raise SystemExit("Acceptance failed: persisted routing does not prove a real non-mock model.")
    if report["parent_status"] != "completed":
        raise SystemExit(f"Acceptance failed: run status is {report['parent_status']}.")
    print("ACCEPTANCE RESULT: read-only Coding Specialist dogfood completed.")


if __name__ == "__main__":
    asyncio.run(run_live_dogfood())
