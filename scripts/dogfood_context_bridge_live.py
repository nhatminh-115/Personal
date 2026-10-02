"""Live research-to-Context-Bridge-to-new-chat dogfood.

Requires explicit OpenAI credentials and RESEARCH_PROVIDER_MODE=live. It uses only AURA's
Research Specialist and native workspace graph; optional code-graph providers are irrelevant.
The JSON artifact records IDs, model decisions, tool names, and context manifest, never source text.
"""
import asyncio
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any, Mapping

RESEARCH_PROMPT = (
    "Research reliable prior work on retrieval-augmented generation evaluation and identify one "
    "narrow, source-supported finding about how retrieval quality is measured. Inspect at least one "
    "source and record evidence with a locator. Separate verified claims from uncertainty. Do not "
    "write files or use code-graph capabilities."
)
MERGE_PROMPT = (
    "Use only the selected Context Bridge. Summarize its verified research conclusion, name the "
    "source locator it provides, and state any qualification. Do not search or infer facts absent "
    "from the bridge."
)


def live_environment_error(environ: Mapping[str, str] | None = None) -> str | None:
    values = os.environ if environ is None else environ
    if values.get("MODEL_PROVIDER", "").strip().lower() != "openai":
        return "Context-Bridge live dogfood requires MODEL_PROVIDER=openai; mock routing is not accepted."
    if not values.get("OPENAI_API_KEY", "").strip():
        return "Context-Bridge live dogfood requires OPENAI_API_KEY; no model call was made."
    if values.get("RESEARCH_PROVIDER_MODE", "").strip().lower() != "live":
        return "Context-Bridge live dogfood requires RESEARCH_PROVIDER_MODE=live."
    return None


def _payload(event: Any) -> dict[str, Any]:
    value = getattr(event, "payload", None)
    return value if isinstance(value, dict) else {}


def _model_decisions(events: list[Any]) -> list[dict[str, Any]]:
    fields = ("agent_role", "provider", "model", "profile_id", "profile_version", "winning_scope", "selection_reason")
    return [
        {key: payload[key] for key in fields if payload.get(key) is not None}
        for event in events
        if getattr(event, "event_type", None) == "model_selected"
        for payload in [_payload(event)]
    ]


def _safe_run_trace(events: list[Any]) -> dict[str, Any]:
    tools = []
    failures = []
    for event in events:
        kind = getattr(event, "event_type", "")
        payload = _payload(event)
        tool = payload.get("tool") or payload.get("tool_name")
        if kind == "tool_executed" and isinstance(tool, str):
            tools.append(tool)
        elif kind in {"tool_failed", "run_failed"}:
            failures.append({"kind": kind, "category": payload.get("error_category", "unknown")})
    return {"tool_sequence": tools, "failures": failures}


def _safe_context_manifest(events: list[Any], bridge_id: str) -> dict[str, Any] | None:
    event = next((item for item in events if getattr(item, "event_type", None) == "context_compiled"), None)
    if event is None:
        return None
    payload = _payload(event)
    allowed = (
        "objects", "estimated_tokens", "character_count", "privacy_requirement", "privacy_sources",
        "required_capabilities", "required_tool_capabilities", "resolved_tool_names", "capability_requirements",
    )
    manifest = {key: payload[key] for key in allowed if key in payload}
    objects = manifest.get("objects", [])
    manifest["bridge_only"] = (
        isinstance(objects, list)
        and len(objects) == 1
        and isinstance(objects[0], dict)
        and objects[0].get("object_id") == bridge_id
        and objects[0].get("object_type") == "context_bridge"
    )
    return manifest


def configure_isolated_runtime(run_key: str) -> None:
    from sqlalchemy.engine import URL

    data_dir = Path(".aura_dogfood").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = URL.create("sqlite+aiosqlite", database=str(data_dir / f"bridge-{run_key}.db")).render_as_string(hide_password=False)
    checkpoint_path = data_dir / f"bridge-{run_key}-checkpoints.db"
    os.environ["DATABASE_URL"] = database_url
    os.environ["CHECKPOINT_DB_PATH"] = str(checkpoint_path)
    os.environ["RESEARCH_PROVIDER_MODE"] = "live"

    from app.core.settings import settings
    settings.DATABASE_URL = database_url
    settings.CHECKPOINT_DB_PATH = checkpoint_path
    settings.MODEL_PROVIDER = "openai"
    settings.RESEARCH_PROVIDER_MODE = "live"

    from app.db import session as db_session
    db_session.configure_engine(database_url)


async def _research_sources(project_name: str, parent_run_id: str) -> tuple[str, list[Any], list[Any]]:
    from sqlalchemy import select
    from app.db.models import DelegationModel, WorkspaceObjectModel
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        result = await db.execute(
            select(DelegationModel)
            .where(DelegationModel.parent_run_id == parent_run_id)
            .order_by(DelegationModel.created_at.asc(), DelegationModel.id.asc())
        )
        delegation = next((row for row in result.scalars() if row.specialist_name == "research"), None)
        if delegation is None:
            raise ValueError("Root run did not persist a Research Specialist child.")
        claims_result = await db.execute(
            select(WorkspaceObjectModel)
            .where(
                WorkspaceObjectModel.project_name == project_name,
                WorkspaceObjectModel.object_type == "research_claim",
            )
            .order_by(WorkspaceObjectModel.created_at.asc(), WorkspaceObjectModel.id.asc())
        )
        claims = [
            item for item in claims_result.scalars()
            if (item.metadata_json or {}).get("verification_status") == "verified"
            and (item.metadata_json or {}).get("evidence_object_ids")
        ]
        if not claims:
            raise ValueError("Research run produced no verified claim linked to persisted evidence.")
        claim = claims[0]
        evidence_ids = (claim.metadata_json or {}).get("evidence_object_ids", [])[:3]
        evidence_result = await db.execute(
            select(WorkspaceObjectModel)
            .where(
                WorkspaceObjectModel.project_name == project_name,
                WorkspaceObjectModel.object_type == "research_evidence",
                WorkspaceObjectModel.id.in_(evidence_ids),
            )
            .order_by(WorkspaceObjectModel.created_at.asc(), WorkspaceObjectModel.id.asc())
        )
        evidence = list(evidence_result.scalars())
        if not evidence:
            raise ValueError("Verified research claim has no persisted evidence objects.")
        return delegation.child_run_id, [claim], evidence


async def _read_run_trace(run_id: str) -> tuple[Any, list[Any]]:
    from sqlalchemy import select
    from app.db.models import RunEventModel, RunModel
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        run = await db.get(RunModel, run_id)
        result = await db.execute(
            select(RunEventModel).where(RunEventModel.run_id == run_id).order_by(RunEventModel.created_at.asc())
        )
        return run, list(result.scalars())


async def run_live_dogfood() -> None:
    error = live_environment_error()
    if error:
        print(f"REAL CONTEXT-BRIDGE DOGFOOD NOT EXECUTED — {error}")
        raise SystemExit(2)

    run_key = uuid.uuid4().hex[:12]
    project_name = f"bridge-dogfood-{run_key}"
    research_session = f"sess-bridge-research-{run_key}"
    merge_session = f"sess-bridge-merge-{run_key}"
    configure_isolated_runtime(run_key)

    from app.api.server import create_app, lifespan
    from app.core.settings import settings
    from app.orchestrator.graph import init_checkpointer
    import httpx

    await init_checkpointer(settings.CHECKPOINT_DB_PATH)
    app = create_app()
    started = time.monotonic()
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=300.0) as client:
            project_response = await client.post("/v1/workspace/projects", json={"name": project_name})
            if project_response.status_code != 201:
                raise SystemExit(f"Workspace project creation failed with HTTP {project_response.status_code}.")
            research_response = await client.post("/v1/chat", json={
                "session_id": research_session,
                "project_name": project_name,
                "task_type": "research",
                "message": RESEARCH_PROMPT,
            })
            if research_response.status_code != 200:
                raise SystemExit(f"Research /v1/chat failed with HTTP {research_response.status_code}.")
            research_payload = research_response.json()
            research_run_id = research_payload.get("run_id")
            if research_payload.get("status") != "completed" or not isinstance(research_run_id, str):
                raise SystemExit(f"Research run did not complete: {research_payload.get('status', 'unknown')}.")
            child_run_id, claims, evidence = await _research_sources(project_name, research_run_id)
            claim = claims[0]
            evidence_ids = [item.id for item in evidence]
            source_ids = [claim.id, *evidence_ids]
            claim_metadata = claim.metadata_json or {}
            bridge_sections = {
                "conclusions": claim.content,
                "observations": "",
                "failed": "",
                "artifacts": "\n".join(
                    f"{item.title} — {(item.metadata_json or {}).get('source_locator', 'locator unavailable')}"
                    for item in evidence
                ),
                "constraints": "",
                "decisions": "",
            }
            bridge_response = await client.post(
                f"/v1/workspace/projects/{project_name}/objects",
                json={
                    "object_type": "context_bridge",
                    "title": f"Research handoff · {run_key}",
                    "content": "Selected verified research claim and source locators from this dogfood run.",
                    "metadata_json": {
                        "bridge_options": {
                            "conclusions": True, "observations": False, "failed": False,
                            "artifacts": True, "constraints": False, "decisions": False,
                        },
                        "bridge_sections": bridge_sections,
                        "origin_research_run_id": research_run_id,
                        "origin_claim_id": claim_metadata.get("claim_id"),
                    },
                    "source_object_ids": source_ids,
                },
            )
            if bridge_response.status_code != 201:
                raise SystemExit(f"Context Bridge creation failed with HTTP {bridge_response.status_code}.")
            bridge_id = bridge_response.json().get("id")
            if not isinstance(bridge_id, str):
                raise SystemExit("Context Bridge endpoint returned no durable object ID.")
            merge_response = await client.post("/v1/chat", json={
                "session_id": merge_session,
                "project_name": project_name,
                "message": MERGE_PROMPT,
                "context_object_ids": [bridge_id],
            })
            if merge_response.status_code != 200:
                raise SystemExit(f"Bridge merge /v1/chat failed with HTTP {merge_response.status_code}.")
            merge_payload = merge_response.json()
            merge_run_id = merge_payload.get("run_id")
            if merge_payload.get("status") != "completed" or not isinstance(merge_run_id, str):
                raise SystemExit(f"Bridge merge run did not complete: {merge_payload.get('status', 'unknown')}.")

        research_parent, research_events = await _read_run_trace(research_run_id)
        research_child, child_events = await _read_run_trace(child_run_id)
        merge_run, merge_events = await _read_run_trace(merge_run_id)

    context_manifest = _safe_context_manifest(merge_events, bridge_id)
    report = {
        "scenario": "research_context_bridge_merge",
        "project_name": project_name,
        "research_run_id": research_run_id,
        "research_child_run_id": child_run_id,
        "research_status": getattr(research_parent, "status", "missing"),
        "research_child_status": getattr(research_child, "status", "missing"),
        "research_routing_decisions": _model_decisions(research_events),
        "research_child_routing_decisions": _model_decisions(child_events),
        "research_tools": _safe_run_trace(research_events),
        "research_child_tools": _safe_run_trace(child_events),
        "selected_research_object_ids": source_ids,
        "bridge_object_id": bridge_id,
        "merge_run_id": merge_run_id,
        "merge_status": getattr(merge_run, "status", "missing"),
        "merge_tools": _safe_run_trace(merge_events),
        "merge_routing_decisions": _model_decisions(merge_events),
        "context_manifest": context_manifest,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    output_dir = Path("artifacts/dogfood").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"context-bridge-{research_run_id}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Audit artifact: {report_path}")

    accepted = (
        report["research_status"] == "completed"
        and report["research_child_status"] == "completed"
        and report["merge_status"] == "completed"
        and context_manifest is not None
        and context_manifest["bridge_only"]
        and any(item.get("provider") not in (None, "mock") for item in report["merge_routing_decisions"])
    )
    if not accepted:
        raise SystemExit("Acceptance failed: persisted research lineage, bridge-only context, or live routing was not proven.")
    print("ACCEPTANCE RESULT: verified research findings crossed a durable Context Bridge into a new live chat.")


if __name__ == "__main__":
    asyncio.run(run_live_dogfood())
