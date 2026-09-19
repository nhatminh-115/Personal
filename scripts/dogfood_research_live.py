"""AURA Real-World Scholarly Research Specialist Live Agent Dogfood Script.

Executes the REAL AURA Agent through the canonical FastAPI /v1/chat API:
User Request
  -> /v1/chat API
  -> Root Personal Orchestrator
  -> delegate_task
  -> Research Specialist child run
  -> ModelRouter
  -> REAL non-mock model (OpenAI)
  -> research_search (live CompositeResearchProvider: Semantic Scholar + arXiv)
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
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import uuid
import httpx
from sqlalchemy import select

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RESEARCH_WORKLOAD = (
    "Investigate prior work on LLM architectures that maintain or update a compact persistent "
    "internal state during inference instead of relying only on an ever-growing KV cache. "
    "Focus on mechanisms involving test-time training, learned memory, recurrent/state-space updates, "
    "or compressed latent state. Identify the closest technical overlaps, inspect the actual methods "
    "of the strongest matches when full text is available, and determine which parts of the proposed "
    "direction are already established versus insufficiently verified."
)
PROJECT_NAME = "Stateful_LLM_Architecture"

DOGFOOD_DATABASE_URL = "sqlite+aiosqlite:///aura_dogfood_live.db"
DOGFOOD_CHECKPOINT_DB_PATH = "./aura_dogfood_live_checkpoints.db"


def validate_live_dogfood_environment() -> None:
    """Enforces fail-fast guards for live dogfood execution."""
    research_provider_mode = os.environ.get("RESEARCH_PROVIDER_MODE", "").lower()
    if research_provider_mode != "live":
        print("\n" + "=" * 80)
        print("ERROR: scripts/dogfood_research_live.py requires RESEARCH_PROVIDER_MODE=live")
        print("Run with: $env:RESEARCH_PROVIDER_MODE='live'; python scripts/dogfood_research_live.py")
        print("=" * 80 + "\n")
        sys.exit(1)

    model_provider = os.environ.get("MODEL_PROVIDER", "").lower()
    if model_provider == "mock":
        print("\n" + "=" * 80)
        print("ERROR: Live agent dogfood requires a non-mock model provider.")
        print("MODEL_PROVIDER is set to 'mock'. Mock provider is strictly prohibited for live agent dogfood.")
        print("=" * 80 + "\n")
        sys.exit(1)

    openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if model_provider == "openai" and not openai_api_key:
        print("\n" + "=" * 80)
        print("ERROR: Live agent dogfood requires a non-mock model provider with valid credentials.")
        print("MODEL_PROVIDER='openai' but OPENAI_API_KEY is missing or empty.")
        print("=" * 80)
        print("REAL AGENT DOGFOOD NOT EXECUTED — missing model credentials")
        print("=" * 80 + "\n")
        sys.exit(1)

    if not model_provider or model_provider not in {"openai"}:
        print("\n" + "=" * 80)
        print(f"ERROR: Live agent dogfood requires a supported non-mock model provider (got: '{model_provider}').")
        print("Supported path: MODEL_PROVIDER=openai with OPENAI_API_KEY set.")
        print("=" * 80)
        print("REAL AGENT DOGFOOD NOT EXECUTED — missing model credentials")
        print("=" * 80 + "\n")
        sys.exit(1)


def configure_dogfood_runtime() -> None:
    """Configures the isolated dogfood environment and initializes runtime singletons."""
    os.environ["DATABASE_URL"] = DOGFOOD_DATABASE_URL
    os.environ["CHECKPOINT_DB_PATH"] = DOGFOOD_CHECKPOINT_DB_PATH

    # Clean up previous dogfood db artifacts if any
    for p in ["aura_dogfood_live.db", "aura_dogfood_live_checkpoints.db"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass

    from app.core.settings import settings
    settings.DATABASE_URL = DOGFOOD_DATABASE_URL
    settings.CHECKPOINT_DB_PATH = Path(DOGFOOD_CHECKPOINT_DB_PATH).resolve()

    from app.db import session as db_session
    db_session.configure_engine(DOGFOOD_DATABASE_URL)


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
        raise ValueError(f"Traces prove delegate_task was NOT executed by root orchestrator for run '{parent_run_id}'!")

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
        .order_by(RunEventModel.created_at.asc())
    )
    root_events = list((await db.execute(root_events_stmt)).scalars().all())

    # Child run events
    child_events_stmt = (
        select(RunEventModel)
        .where(RunEventModel.run_id == child_run_id)
        .order_by(RunEventModel.created_at.asc())
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

    print("\nActual Model-Generated Search Queries:")
    for q in r_state.queries:
        print(f"  - '{q.query_text}' (Type: {q.search_type}, Iteration: {q.iteration}, Results: {q.results_count})")

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
        print(f"    Quote: \"{ev.extracted_text[:120]}...\"")

    print(f"Actual ResearchClaim IDs  : {[c.claim_id for c in r_state.claims]}")
    for c in r_state.claims:
        print(f"  [OK] [{c.claim_id}] Type={c.claim_type.value}: \"{c.claim_text}\" (Cites: {c.evidence_ids})")

    print(f"Project Memories Stored   : {len(mem_records)} in '{PROJECT_NAME}'")
    for m in mem_records:
        print(f"  - Memory ID: {m.id} | Key: {m.key}")
        print(f"    Content: {m.content[:100]}...")
        meta = m.metadata_json or {}
        print(f"    Lineage: Claims={meta.get('claim_ids')}, Evidence={meta.get('evidence_ids')}, Sources={meta.get('sources_cited')}")

    if elapsed_seconds is not None:
        print(f"Total Elapsed Time        : {elapsed_seconds:.2f}s")
    print("=" * 80)
    print("ACCEPTANCE RESULT: Audit completed successfully.")
    print("=" * 80 + "\n")

    return {
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
        "memory_count": len(mem_records),
    }


async def run_live_agent_dogfood():
    # 1. Validate live credentials fail-fast
    validate_live_dogfood_environment()

    # 2. Configure isolated dogfood runtime environment and singletons
    configure_dogfood_runtime()

    # 3. Only then import modules that depend on settings/runtime
    from app.api.server import create_app, lifespan
    from app.core.settings import settings
    from app.db import session as db_session
    from app.orchestrator.graph import init_checkpointer

    overall_start_time = time.time()
    print("=" * 80)
    print("AURA SCHOLARLY RESEARCH SPECIALIST: LIVE END-TO-END AGENT DOGFOOD")
    print(f"Model Provider        : {settings.MODEL_PROVIDER} ({settings.OPENAI_MODEL_NAME})")
    print(f"Research Provider Mode: {settings.RESEARCH_PROVIDER_MODE} (Live Semantic Scholar + arXiv)")
    print(f"Target Project        : {PROJECT_NAME}")
    print(f"Isolated Database URL : {settings.DATABASE_URL}")
    print(f"Isolated Checkpoints  : {settings.CHECKPOINT_DB_PATH}")
    print("=" * 80)

    # Initialize checkpointer against isolated path
    await init_checkpointer(settings.CHECKPOINT_DB_PATH)

    app = create_app()
    session_id = f"sess-dogfood-{uuid.uuid4().hex[:8]}"

    print("\n[Phase 1] Starting application lifecycle and sending research workload to /v1/chat...")
    print(f"Workload:\n\"{RESEARCH_WORKLOAD}\"\n")

    parent_run_id = None
    chat_response_data = None

    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=300.0) as client:
            t0 = time.time()
            chat_resp = await client.post(
                "/v1/chat",
                json={
                    "session_id": session_id,
                    "message": RESEARCH_WORKLOAD,
                    "project_name": PROJECT_NAME,
                },
            )
            chat_duration = time.time() - t0

            if chat_resp.status_code != 200:
                print(f"\n[ERROR] /v1/chat failed with status {chat_resp.status_code}: {chat_resp.text}")
                sys.exit(1)

            chat_response_data = chat_resp.json()
            parent_run_id = chat_response_data.get("run_id")
            run_status = chat_response_data.get("status")

            print(f" -> Initial /v1/chat returned status='{run_status}' in {chat_duration:.2f}s (run_id='{parent_run_id}')")

            # Handle approval flow via real API contract: POST /v1/approvals/{approval_id}/decision
            approval_cycles = 0
            max_approval_cycles = 10
            current_approval_id = chat_response_data.get("approval_id")

            while run_status == "waiting_for_approval" and current_approval_id and approval_cycles < max_approval_cycles:
                approval_cycles += 1
                print(f"\n[Approval {approval_cycles}/{max_approval_cycles}] Run requires authorization (approval_id='{current_approval_id}'). Submitting approval decision...")
                appr_resp = await client.post(
                    f"/v1/approvals/{current_approval_id}/decision",
                    json={
                        "decision": "approved",
                        "decision_notes": "Live dogfood approval",
                    },
                )
                if appr_resp.status_code != 200:
                    print(f"[ERROR] /v1/approvals/{current_approval_id}/decision failed: {appr_resp.text}")
                    sys.exit(1)

                decision_data = appr_resp.json()
                run_status = decision_data.get("execution_status")
                current_approval_id = decision_data.get("approval_id") if run_status == "waiting_for_approval" else None
                if decision_data.get("final_response"):
                    chat_response_data["response"] = decision_data.get("final_response")
                print(f" -> Decision processed. Execution status='{run_status}'")

            if run_status == "waiting_for_approval":
                print("[ERROR] Max approval cycles reached but run is still waiting for approval.")
                sys.exit(1)

    print("\n" + "-" * 80)
    print("ROOT ORCHESTRATOR SYNTHESIS RESPONSE:")
    print("-" * 80)
    final_text = chat_response_data.get("response", "")
    print(final_text if final_text else "[No response text returned]")
    print("-" * 80)

    # --------------------------------------------------------------------------
    # 2. POST-RUN VERIFICATION & AUDIT TRACE INSPECTION
    # --------------------------------------------------------------------------
    print("\n[Phase 2] Inspecting Database Lineage, Checkpoints & Audit Traces...")
    elapsed = time.time() - overall_start_time
    await audit_dogfood_run(parent_run_id=parent_run_id, elapsed_seconds=elapsed)


if __name__ == "__main__":
    asyncio.run(run_live_agent_dogfood())
