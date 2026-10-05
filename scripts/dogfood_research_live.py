"""AURA Real-World Scholarly Research Specialist Live Agent Dogfood Script.

Executes the REAL AURA Agent through the canonical FastAPI /v1/chat API:
User Request
  -> /v1/chat API
  -> Root Personal Orchestrator
  -> delegate_task
  -> Research Specialist child run
  -> ModelRouter
  -> REAL non-mock model (OpenAI)
  -> research_search (live CompositeResearchProvider: Semantic Scholar + arXiv + Crossref metadata fallback)
  -> read_document_section (arXiv PDF extraction & section parsing)
  -> extract_evidence
  -> record_research_claim
  -> save_research_finding
  -> validated ResearchResult
  -> Root Orchestrator synthesis response

CRITICAL REQUIREMENTS:
- Must NOT run when MODEL_PROVIDER=mock (fails fast).
- Must NOT run when OPENAI_API_KEY is missing (fails fast with explicit notice).
- Must NOT manually invoke research tools, screen papers with hardcoded strings, or create synthetic claims.
- The real non-mock model decides queries, source selection, evidence extraction, and claims.
- Module-level imports must remain safe and NOT initialize AURA settings or databases.
"""

import asyncio
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import uuid
import httpx
from sqlalchemy import select
from urllib.parse import urlparse

if __package__:
    from ._bootstrap import ensure_project_root, resolve_project_path
else:
    from _bootstrap import ensure_project_root, resolve_project_path

PROJECT_ROOT = ensure_project_root(__file__)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RESEARCH_WORKLOAD = (
    "You are the AURA root orchestrator. Delegate this request now to the Research Specialist "
    "using delegate_task with specialist_name='research'; do not investigate or answer directly. "
    "Ask the specialist to investigate prior work on LLM architectures that maintain or update a compact persistent "
    "internal state during inference instead of relying only on an ever-growing KV cache. "
    "Focus on mechanisms involving test-time training, learned memory, recurrent/state-space updates, "
    "or compressed latent state. Identify the closest technical overlaps, inspect the actual methods "
    "of the strongest matches when full text is available, and determine which parts of the proposed "
    "direction are already established versus insufficiently verified."
)


def dogfood_acceptance_failures(report: Dict[str, Any]) -> list[str]:
    """Return unmet end-to-end research invariants for the live dogfood run."""
    failures: list[str] = []
    if report.get("specialist_name") != "research":
        failures.append("root did not delegate to the Research Specialist")
    if report.get("delegation_status") != "completed" or report.get("child_run_status") != "completed":
        failures.append("Research Specialist delegation did not complete")
    if not report.get("actual_model_provider") or report.get("actual_model_provider") == "unknown":
        failures.append("no actual provider/model selection was recorded")
    if not report.get("actual_model_name") or report.get("actual_model_name") == "unknown":
        failures.append("no actual provider/model selection was recorded")
    if report.get("model_call_count", 0) < 1:
        failures.append("Research Specialist made no recorded model call")

    tool_sequence = set(report.get("tool_sequence", []))
    for tool in ("research_search", "extract_evidence", "record_research_claim"):
        if tool not in tool_sequence:
            failures.append(f"required research tool was not recorded: {tool}")

    if report.get("research_state_status") != "completed":
        failures.append(
            "checkpointed research did not complete "
            f"(status: {report.get('research_state_status', 'unknown')})"
        )
    for key, label in (
        ("sources_count", "canonical source"),
        ("inspected_count", "inspected source"),
        ("evidence_count", "evidence item"),
        ("source_supported_claim_count", "verified source-supported claim"),
        ("provenance_memory_count", "claim/evidence-linked project memory"),
    ):
        if report.get(key, 0) < 1:
            failures.append(f"no {label} was persisted")
    return failures
PROJECT_NAME = "Stateful_LLM_Architecture"

def live_environment_error(environ: Dict[str, str] | None = None) -> str | None:
    """Return a fail-fast explanation for unsupported live model/research setup."""
    values = os.environ if environ is None else environ
    research_provider_mode = values.get("RESEARCH_PROVIDER_MODE", "").strip().lower()
    if research_provider_mode != "live":
        return "scripts/dogfood_research_live.py requires RESEARCH_PROVIDER_MODE=live."

    model_provider = values.get("MODEL_PROVIDER", "").strip().lower()
    if model_provider != "openai":
        return "Live agent dogfood requires MODEL_PROVIDER=openai; mock routing is not accepted."

    model_override = values.get("AURA_DOGFOOD_MODEL_OVERRIDE", "").strip()
    if model_override.startswith("ollama:"):
        _provider, separator, model = model_override.partition(":")
        if not separator or not model.strip():
            return "AURA_DOGFOOD_MODEL_OVERRIDE must be an exact ollama:model ID."
        local_url = values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip()
        try:
            parsed_url = urlparse(local_url)
            is_loopback = parsed_url.scheme in {"http", "https"} and parsed_url.hostname in {
                "localhost", "127.0.0.1", "::1",
            }
        except ValueError:
            is_loopback = False
        if not is_loopback:
            return "OLLAMA_BASE_URL must point to localhost or a loopback IP for an Ollama model override."
        return None

    if not values.get("OPENAI_API_KEY", "").strip():
        if model_override:
            return "Without an OpenAI key, AURA_DOGFOOD_MODEL_OVERRIDE must be an exact ollama:model ID."
        return "Live agent dogfood requires OPENAI_API_KEY or an explicit loopback Ollama override."
    return None


def validate_live_dogfood_environment() -> None:
    """Enforces fail-fast guards for live dogfood execution."""
    error = live_environment_error()
    if error:
        print("\n" + "=" * 80)
        print(f"ERROR: {error}")
        print("REAL AGENT DOGFOOD NOT EXECUTED — live model/research requirements were not met")
        print("=" * 80 + "\n")
        sys.exit(2)


def _chat_request_payload(session_id: str, project_name: str, environ: Dict[str, str] | None = None) -> Dict[str, str]:
    values = os.environ if environ is None else environ
    payload = {
        "session_id": session_id,
        "message": RESEARCH_WORKLOAD,
        "project_name": project_name,
    }
    model_override = values.get("AURA_DOGFOOD_MODEL_OVERRIDE", "").strip()
    if model_override:
        payload["model_override"] = model_override
        if model_override.startswith("ollama:"):
            payload["reasoning_override"] = "instant"
    return payload


def configure_dogfood_runtime(run_key: str, state_dir: Path | None = None) -> tuple[str, Path]:
    """Configure unique run-scoped storage without deleting prior dogfood evidence."""
    from sqlalchemy.engine import URL

    data_dir = resolve_project_path(PROJECT_ROOT, state_dir if state_dir is not None else ".aura_dogfood")
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / f"research-{run_key}.db"
    checkpoint_path = data_dir / f"research-{run_key}-checkpoints.db"
    database_url = URL.create(
        "sqlite+aiosqlite", database=str(database_path)
    ).render_as_string(hide_password=False)
    os.environ["DATABASE_URL"] = database_url
    os.environ["CHECKPOINT_DB_PATH"] = str(checkpoint_path)

    from app.core.settings import settings
    settings.DATABASE_URL = database_url
    settings.CHECKPOINT_DB_PATH = checkpoint_path

    from app.db import session as db_session
    db_session.configure_engine(database_url)
    return database_url, checkpoint_path


def pending_approval_report(run_id: str, approval_id: str) -> Dict[str, Any]:
    """Describe a paused live run without approving or recording a decision."""
    return {
        "scenario": "research_live_dogfood",
        "run_id": run_id,
        "status": "waiting_for_approval",
        "approval_id": approval_id,
        "approval_decision_submitted": False,
    }


def write_pending_approval_report(run_id: str, approval_id: str, output_dir: Path | None = None) -> Path:
    report = pending_approval_report(run_id, approval_id)
    directory = resolve_project_path(PROJECT_ROOT, output_dir if output_dir is not None else "artifacts/dogfood")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"research-pending-approval-{run_id}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


async def latest_run_id_for_session(session_id: str, db: Any | None = None) -> str | None:
    """Find a persisted run when /v1/chat fails before returning its run ID."""
    from app.db.models import RunModel
    from app.db.session import async_session_factory

    if db is None:
        async with async_session_factory() as session:
            return await latest_run_id_for_session(session_id, db=session)
    result = await db.execute(
        select(RunModel.id)
        .where(RunModel.session_id == session_id, RunModel.parent_run_id.is_(None))
        .order_by(RunModel.created_at.desc(), RunModel.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def failed_run_report(
    session_id: str,
    *,
    parent_run_id: str | None = None,
    http_status: int | None = None,
    elapsed_seconds: float | None = None,
    failure: str,
) -> Dict[str, Any]:
    """Build a safe failure artifact without raw HTTP, prompt, or source content."""
    report: Dict[str, Any] = {
        "scenario": "research_live_dogfood",
        "session_id": session_id,
        "parent_run_id": parent_run_id,
        "accepted": False,
        "acceptance_failures": [failure],
    }
    if http_status is not None:
        report["http_status"] = http_status
    if elapsed_seconds is not None:
        report["elapsed_seconds"] = round(elapsed_seconds, 2)
    return report

async def audit_dogfood_run(
    parent_run_id: str,
    db: Optional[Any] = None,
    graph: Optional[Any] = None,
    elapsed_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Inspects persisted database lineage, checkpoints, and audit traces for reporting."""
    from app.db.models import DelegationModel, MemoryModel, RunEventModel, RunModel
    from app.db.session import async_session_factory
    from app.orchestrator.graph import get_compiled_graph
    from app.research.models import ResearchState

    if db is None:
        async with async_session_factory() as session:
            return await audit_dogfood_run(parent_run_id, db=session, graph=graph, elapsed_seconds=elapsed_seconds)

    # 1. Lineage: Verify Root -> Research Specialist delegation
    del_stmt = select(DelegationModel).where(DelegationModel.parent_run_id == parent_run_id)
    del_res = await db.execute(del_stmt)
    delegation = del_res.scalar_one_or_none()

    if not delegation:
        parent_run = await db.get(RunModel, parent_run_id)
        session_id = parent_run.session_id if parent_run else "unknown"
        return failed_run_report(
            session_id,
            parent_run_id=parent_run_id,
            elapsed_seconds=elapsed_seconds,
            failure="root did not persist a delegation to the Research Specialist",
        )

    child_run_id = delegation.child_run_id
    specialist_name = delegation.specialist_name
    delegation_status = delegation.status

    child_run = await db.get(RunModel, child_run_id)
    if not child_run:
        raise ValueError(f"Child run record '{child_run_id}' missing in database!")

    # 2. Audit Traces: Model calls and Tool execution sequence
    # Root run events
    root_events_stmt = (
        select(RunEventModel)
        .where(RunEventModel.run_id == parent_run_id)
        .order_by(RunEventModel.created_at.asc(), RunEventModel.id.asc())
    )
    root_events = list((await db.execute(root_events_stmt)).scalars().all())

    # Child run events
    child_events_stmt = (
        select(RunEventModel)
        .where(RunEventModel.run_id == child_run_id)
        .order_by(RunEventModel.created_at.asc(), RunEventModel.id.asc())
    )
    child_events = list((await db.execute(child_events_stmt)).scalars().all())

    model_calls = [e for e in child_events if e.event_type == "model_called"]
    tool_executions = [e for e in child_events if e.event_type == "tool_executed"]

    actual_model_provider = "unknown"
    actual_model_name = "unknown"
    if model_calls:
        routing_dec = model_calls[0].payload.get("routing_decision", {})
        actual_model_provider = routing_dec.get("provider", "unknown")
        actual_model_name = routing_dec.get("model", "unknown")

    tool_sequence = [e.payload.get("tool") for e in tool_executions if e.payload and e.payload.get("tool")]

    # 3. Checkpointed ResearchState Inspection
    if graph is None:
        graph = await get_compiled_graph()

    child_snapshot = await graph.aget_state({"configurable": {"thread_id": child_run_id}})
    r_state_dict = (
        child_snapshot.values.get("research_state")
        if child_snapshot and hasattr(child_snapshot, "values")
        else None
    )

    r_state = ResearchState.from_dict(r_state_dict) if r_state_dict else ResearchState()

    # 4. Project Memory Inspection
    mem_stmt = select(MemoryModel).where(MemoryModel.project_name == PROJECT_NAME)
    mem_records = list((await db.execute(mem_stmt)).scalars().all())

    # 5. Parse validated synthesis status from delegation result_summary
    parsed_synthesis_status = "unknown"
    summary_text = getattr(delegation, "result_summary", None) or getattr(delegation, "summary", None)
    if summary_text:
        for line in summary_text.splitlines():
            if "Research Status:" in line:
                parsed_synthesis_status = line.split("Research Status:", 1)[1].strip()
                break

    # 6. Format and display telemetry report
    print("\n" + "=" * 80)
    print("LIVE AGENT RESEARCH DOGFOOD ACCEPTANCE REPORT")
    print("=" * 80)
    print(f"Parent Run ID             : {parent_run_id}")
    print(f"Child Specialist Run ID   : {child_run_id}")
    print(f"Specialist Name           : {specialist_name}")
    print(f"Actual Model Provider     : {actual_model_provider}")
    print(f"Actual Model Name         : {actual_model_name}")
    print(f"Model Call Count          : {len(model_calls)}")
    print(f"Tool-Call Sequence        : {' -> '.join(tool_sequence) if tool_sequence else 'None'}")
    print(f"Child Run Status          : {child_run.status}")
    print(f"Delegation Status         : {delegation_status}")
    print(f"ResearchState Status      : {r_state.status.value}")
    print(f"Parsed Synthesis Status   : {parsed_synthesis_status}")

    print("\nSearch Query Trace:")
    for q in r_state.queries:
        print(f"  - [{q.query_id}] Type: {q.search_type}, Iteration: {q.iteration}, Results: {q.results_count}")

    print(f"\nDiscovered Canonical Sources ({len(r_state.sources)} unified):")
    pdf_count = 0
    abstract_count = 0
    for src in r_state.sources.values():
        provs = src.metadata.get("providers", [src.metadata.get("provider", "unknown")])
        status = src.metadata.get("full_text_status", "unknown")
        if status == "available":
            pdf_count += 1
        else:
            abstract_count += 1
        print(f"  * [{src.canonical_id}] '{src.title[:65]}...' ({src.year})")
        print(f"    Providers: {provs} | Full-Text: {status}")

    print(f"\nInspected Sources ({len(r_state.inspected_source_ids)}):")
    for s_id in r_state.inspected_source_ids:
        src = r_state.sources.get(s_id)
        title = src.title if src else s_id
        print(f"  - [{s_id}] {title}")

    print(f"\nPDF/Full-Text Availability: Available/Parsed={pdf_count}, Abstract-Only={abstract_count}")
    print(f"Actual EvidenceItem IDs   : {list(r_state.evidence.keys())}")
    for eid, ev in r_state.evidence.items():
        print(f"  + [{eid}] Locator: {ev.source_locator}")

    print(f"Actual ResearchClaim IDs  : {[c.claim_id for c in r_state.claims]}")
    for c in r_state.claims:
        print(f"  [OK] [{c.claim_id}] Type={c.claim_type.value} (Cites: {c.evidence_ids})")

    print(f"Project Memories Stored   : {len(mem_records)} in '{PROJECT_NAME}'")
    for m in mem_records:
        meta = m.metadata_json or {}
        print(f"  - Memory ID: {m.id} | Lineage: Claims={meta.get('claim_ids')}, Evidence={meta.get('evidence_ids')}, Sources={meta.get('sources_cited')}")

    claim_ids = {claim.claim_id for claim in r_state.claims}
    evidence_ids = set(r_state.evidence)
    source_supported_claim_count = sum(
        claim.claim_type.value == "source_supported_fact"
        and claim.verification_status == "verified"
        and bool(set(claim.evidence_ids) & evidence_ids)
        for claim in r_state.claims
    )
    provenance_memory_count = sum(
        bool(set((memory.metadata_json or {}).get("claim_ids", [])) & claim_ids)
        and bool(set((memory.metadata_json or {}).get("evidence_ids", [])) & evidence_ids)
        for memory in mem_records
    )

    if elapsed_seconds is not None:
        print(f"Total Elapsed Time        : {elapsed_seconds:.2f}s")
    print("=" * 80)
    report = {
        "parent_run_id": parent_run_id,
        "child_run_id": child_run_id,
        "specialist_name": specialist_name,
        "actual_model_provider": actual_model_provider,
        "actual_model_name": actual_model_name,
        "model_call_count": len(model_calls),
        "tool_sequence": tool_sequence,
        "child_run_status": child_run.status,
        "delegation_status": delegation_status,
        "research_state_status": r_state.status.value,
        "parsed_synthesis_status": parsed_synthesis_status,
        "queries_count": len(r_state.queries),
        "sources_count": len(r_state.sources),
        "inspected_count": len(r_state.inspected_source_ids),
        "evidence_count": len(r_state.evidence),
        "claims_count": len(r_state.claims),
        "source_supported_claim_count": source_supported_claim_count,
        "memory_count": len(mem_records),
        "provenance_memory_count": provenance_memory_count,
    }
    failures = dogfood_acceptance_failures(report)
    report["accepted"] = not failures
    report["acceptance_failures"] = failures
    if failures:
        print("ACCEPTANCE RESULT: FAIL")
        for failure in failures:
            print(f"  - {failure}")
    else:
        print("ACCEPTANCE RESULT: PASS — persisted research evidence, verified claims, and memory provenance.")
    print("=" * 80 + "\n")
    return report


def write_audit_report(parent_run_id: str, report: Dict[str, Any], output_dir: Path | None = None) -> Path:
    """Persist the sanitized audit summary without source text or model output."""
    directory = resolve_project_path(PROJECT_ROOT, output_dir if output_dir is not None else "artifacts/dogfood")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"research-{parent_run_id}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


async def run_live_agent_dogfood():
    # 1. Validate live credentials fail-fast
    validate_live_dogfood_environment()

    # 2. Configure unique isolated dogfood runtime state for this run
    run_key = uuid.uuid4().hex[:12]
    database_url, checkpoint_path = configure_dogfood_runtime(run_key)

    # 3. Only then import modules that depend on settings/runtime
    from app.api.server import create_app, lifespan
    from app.core.settings import settings
    from app.db import session as db_session
    from app.orchestrator.graph import init_checkpointer

    overall_start_time = time.time()
    print("=" * 80)
    print("AURA SCHOLARLY RESEARCH SPECIALIST: LIVE END-TO-END AGENT DOGFOOD")
    selected_model = os.environ.get("AURA_DOGFOOD_MODEL_OVERRIDE") or (
        f"{settings.MODEL_PROVIDER}:{settings.OPENAI_MODEL_NAME}"
    )
    print(f"Model Selection       : {selected_model}")
    print(f"Research Provider Mode: {settings.RESEARCH_PROVIDER_MODE} (Live Semantic Scholar + arXiv + Crossref metadata)")
    print(f"Target Project        : {PROJECT_NAME}")
    print(f"Isolated Database URL : {database_url}")
    print(f"Isolated Checkpoints  : {checkpoint_path}")
    print("=" * 80)

    # Initialize checkpointer against isolated path
    await init_checkpointer(settings.CHECKPOINT_DB_PATH)

    app = create_app()
    session_id = f"sess-dogfood-{uuid.uuid4().hex[:8]}"

    print("\n[Phase 1] Starting application lifecycle and sending research workload to /v1/chat...")
    print(f"Workload:\n\"{RESEARCH_WORKLOAD}\"\n")

    parent_run_id: str | None = None
    chat_response_data: Dict[str, Any] = {}
    http_failure_status: int | None = None

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=300.0) as client:
            t0 = time.time()
            chat_resp = await client.post(
                "/v1/chat",
                json=_chat_request_payload(session_id, PROJECT_NAME),
            )
            chat_duration = time.time() - t0

            if chat_resp.status_code != 200:
                http_failure_status = chat_resp.status_code
                parent_run_id = await latest_run_id_for_session(session_id)
                print(
                    f"\n[ERROR] /v1/chat returned HTTP {http_failure_status}; "
                    f"persisted run found={isinstance(parent_run_id, str)}."
                )
            else:
                chat_response_data = chat_resp.json()
                parent_run_id = chat_response_data.get("run_id")
                run_status = chat_response_data.get("status")

                print(f" -> Initial /v1/chat returned status='{run_status}' in {chat_duration:.2f}s (run_id='{parent_run_id}')")

                pending_approval_id = (
                    chat_response_data.get("approval_id")
                    if run_status == "waiting_for_approval"
                    else None
                )

    if http_failure_status is None:
        final_text = chat_response_data.get("response", "")
        print(f"Root response recorded ({len(final_text)} characters); response text omitted from dogfood output.")

    pending_approval_id = chat_response_data.get("approval_id") if chat_response_data.get("status") == "waiting_for_approval" else None
    if pending_approval_id and parent_run_id:
        pending_report = write_pending_approval_report(parent_run_id, pending_approval_id)
        print(
            "LIVE DOGFOOD PAUSED FOR HUMAN APPROVAL — "
            f"approval_id={pending_approval_id}. No decision was submitted."
        )
        print(f"Pending approval artifact: {pending_report}")
        raise SystemExit(2)

    # --------------------------------------------------------------------------
    # 2. POST-RUN VERIFICATION & AUDIT TRACE INSPECTION
    # --------------------------------------------------------------------------
    print("\n[Phase 2] Inspecting Database Lineage, Checkpoints & Audit Traces...")
    elapsed = time.time() - overall_start_time
    if isinstance(parent_run_id, str):
        try:
            report = await audit_dogfood_run(parent_run_id=parent_run_id, elapsed_seconds=elapsed)
        except ValueError:
            report = failed_run_report(
                session_id,
                parent_run_id=parent_run_id,
                http_status=http_failure_status,
                elapsed_seconds=elapsed,
                failure="persisted Research Specialist lineage could not be audited",
            )
    else:
        report = failed_run_report(
            session_id,
            http_status=http_failure_status,
            elapsed_seconds=elapsed,
            failure="/v1/chat failed before a durable run ID could be recovered",
        )
    report["elapsed_seconds"] = round(elapsed, 2)
    if http_failure_status is not None:
        report["http_status"] = http_failure_status
        report["accepted"] = False
        failures = report.setdefault("acceptance_failures", [])
        http_failure = f"/v1/chat returned HTTP {http_failure_status}"
        if http_failure not in failures:
            failures.append(http_failure)
    report_path = write_audit_report(parent_run_id or session_id, report)
    print(f"Sanitized audit artifact: {report_path}")
    if not report["accepted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(run_live_agent_dogfood())
