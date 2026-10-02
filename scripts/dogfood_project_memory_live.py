"""Credential-gated cross-session project-memory retrieval dogfood.

Seeds harmless, run-scoped project facts, then asks a fresh live chat to retrieve them.
The report contains run/routing/context IDs and match booleans only, never memory text.
"""
import asyncio
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any, Mapping

TARGET_FACT = "A blue-lantern release requires a two-person review and an immediate rollback trigger."
DECOY_FACT = "A blue-lantern release is single-owner and has no rollback trigger."


def live_environment_error(environ: Mapping[str, str] | None = None) -> str | None:
    values = os.environ if environ is None else environ
    if values.get("MODEL_PROVIDER", "").strip().lower() != "openai":
        return "Project-memory live dogfood requires MODEL_PROVIDER=openai; mock routing is not accepted."
    if not values.get("OPENAI_API_KEY", "").strip():
        return "Project-memory live dogfood requires OPENAI_API_KEY; no model call was made."
    return None


def _payload(event: Any) -> dict[str, Any]:
    value = getattr(event, "payload", None)
    return value if isinstance(value, dict) else {}


def _context_summary(events: list[Any], target_memory_id: str, decoy_memory_id: str) -> dict[str, Any]:
    event = next((item for item in events if getattr(item, "event_type", None) == "context_loaded"), None)
    if event is None:
        return {
            "context_event_found": False,
            "target_memory_retrieved": False,
            "foreign_project_memory_retrieved": False,
            "project_memory_count": 0,
        }
    memory_ids = _payload(event).get("project_memory_ids", [])
    if not isinstance(memory_ids, list):
        memory_ids = []
    return {
        "context_event_found": True,
        "target_memory_retrieved": target_memory_id in memory_ids,
        "foreign_project_memory_retrieved": decoy_memory_id in memory_ids,
        "project_memory_count": len(memory_ids),
    }


def _model_decisions(events: list[Any]) -> list[dict[str, Any]]:
    fields = ("agent_role", "provider", "model", "profile_id", "profile_version", "winning_scope", "selection_reason")
    return [
        {key: payload[key] for key in fields if payload.get(key) is not None}
        for event in events
        if getattr(event, "event_type", None) == "model_selected"
        for payload in [_payload(event)]
    ]


def configure_isolated_runtime(run_key: str) -> None:
    from sqlalchemy.engine import URL

    data_dir = Path(".aura_dogfood").resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_url = URL.create("sqlite+aiosqlite", database=str(data_dir / f"memory-{run_key}.db")).render_as_string(hide_password=False)
    checkpoint_path = data_dir / f"memory-{run_key}-checkpoints.db"
    os.environ["DATABASE_URL"] = database_url
    os.environ["CHECKPOINT_DB_PATH"] = str(checkpoint_path)

    from app.core.settings import settings
    settings.DATABASE_URL = database_url
    settings.CHECKPOINT_DB_PATH = checkpoint_path
    settings.MODEL_PROVIDER = "openai"

    from app.db import session as db_session
    db_session.configure_engine(database_url)


async def _seed_project_memories(project_name: str, target_id: str, decoy_project: str, decoy_id: str) -> None:
    from app.db.models import MemoryModel
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        db.add_all([
            MemoryModel(
                id=target_id,
                session_id=None,
                memory_type="project",
                key=f"{project_name}:release_guard",
                content=TARGET_FACT,
                project_name=project_name,
                metadata_json={"source": "isolated_dogfood", "privacy_policy": "internal"},
            ),
            MemoryModel(
                id=decoy_id,
                session_id=None,
                memory_type="project",
                key=f"{decoy_project}:release_guard",
                content=DECOY_FACT,
                project_name=decoy_project,
                metadata_json={"source": "isolated_dogfood", "privacy_policy": "internal"},
            ),
        ])
        await db.commit()


async def _audit_run(run_id: str, target_id: str, decoy_id: str, response_text: str, status: str) -> dict[str, Any]:
    from sqlalchemy import select
    from app.db.models import RunEventModel, RunModel
    from app.db.session import async_session_factory

    async with async_session_factory() as db:
        run = await db.get(RunModel, run_id)
        result = await db.execute(
            select(RunEventModel).where(RunEventModel.run_id == run_id).order_by(RunEventModel.created_at.asc())
        )
        events = list(result.scalars())
        context = _context_summary(events, target_id, decoy_id)
        decisions = _model_decisions(events)
        normalized = " ".join(response_text.lower().replace("-", " ").split())
        return {
            "scenario": "cross_session_project_memory_retrieval",
            "run_id": run_id,
            "run_status": run.status if run is not None else "missing",
            "response_status": status,
            "routing_decisions": decisions,
            **context,
            "answer_contains_two_person_review": "two person review" in normalized,
            "answer_contains_rollback_trigger": "rollback trigger" in normalized,
            "answer_contains_foreign_decoy": "single owner" in normalized,
        }


async def run_live_dogfood() -> None:
    error = live_environment_error()
    if error:
        print(f"REAL PROJECT-MEMORY DOGFOOD NOT EXECUTED — {error}")
        raise SystemExit(2)

    run_key = uuid.uuid4().hex[:12]
    project_name = f"memory-dogfood-{run_key}"
    decoy_project = f"foreign-memory-dogfood-{run_key}"
    target_memory_id, decoy_memory_id = str(uuid.uuid4()), str(uuid.uuid4())
    session_id = f"sess-memory-dogfood-{run_key}"
    configure_isolated_runtime(run_key)

    from app.api.server import create_app, lifespan
    from app.core.settings import settings
    from app.orchestrator.graph import init_checkpointer
    import httpx

    await init_checkpointer(settings.CHECKPOINT_DB_PATH)
    app = create_app()
    started = time.monotonic()
    async with lifespan(app):
        await _seed_project_memories(project_name, target_memory_id, decoy_project, decoy_memory_id)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=180.0) as client:
            response = await client.post("/v1/chat", json={
                "session_id": session_id,
                "project_name": project_name,
                "message": (
                    "Using only this project's persisted memory, what review and rollback guard applies to a "
                    "blue-lantern release? State the rule directly. Do not infer or use unrelated project memory."
                ),
            })
            if response.status_code != 200:
                raise SystemExit(f"/v1/chat failed with HTTP {response.status_code}; inspect the server log.")
            payload = response.json()
            run_id = payload.get("run_id")
            response_status = payload.get("status", "unknown")
            response_text = payload.get("response") or ""
            if not isinstance(run_id, str):
                raise SystemExit("/v1/chat returned no run_id; no durable run can be audited.")
        report = await _audit_run(run_id, target_memory_id, decoy_memory_id, response_text, response_status)

    report["project_name"] = project_name
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    output_dir = Path("artifacts/dogfood").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"project-memory-{run_id}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Audit artifact: {report_path}")

    accepted = (
        report["run_status"] == "completed"
        and report["response_status"] == "completed"
        and report["context_event_found"]
        and report["target_memory_retrieved"]
        and not report["foreign_project_memory_retrieved"]
        and report["answer_contains_two_person_review"]
        and report["answer_contains_rollback_trigger"]
        and not report["answer_contains_foreign_decoy"]
        and any(item.get("provider") not in (None, "mock") for item in report["routing_decisions"])
    )
    if not accepted:
        raise SystemExit("Acceptance failed: project scope, persisted routing, or memory recall was not proven.")
    print("ACCEPTANCE RESULT: cross-session project-memory retrieval completed without foreign-project leakage.")


if __name__ == "__main__":
    asyncio.run(run_live_dogfood())
