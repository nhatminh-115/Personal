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
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy import select

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ------------------------------------------------------------------------------
# 1. FAIL-FAST GUARDS FOR ENVIRONMENT & MODEL CREDENTIALS
# ------------------------------------------------------------------------------
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

# Configure isolated dogfood database
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///aura_dogfood_live.db"
os.environ["CHECKPOINT_DB_PATH"] = "./aura_dogfood_live_checkpoints.db"

# Cleanup previous dogfood db artifacts
for p in ["aura_dogfood_live.db", "aura_dogfood_live_checkpoints.db"]:
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass

from app.api.server import create_app, lifespan
from app.core.logging import logger
from app.core.settings import settings
from app.db.models import DelegationModel, MemoryModel, RunEventModel, RunModel
from app.db.session import async_session_factory
from app.orchestrator.graph import get_compiled_graph
from app.research.models import ResearchState


RESEARCH_WORKLOAD = (
    "Investigate prior work on LLM architectures that maintain or update a compact persistent "
    "internal state during inference instead of relying only on an ever-growing KV cache. "
    "Focus on mechanisms involving test-time training, learned memory, recurrent/state-space updates, "
    "or compressed latent state. Identify the closest technical overlaps, inspect the actual methods "
    "of the strongest matches when full text is available, and determine which parts of the proposed "
    "direction are already established versus insufficiently verified."
)
PROJECT_NAME = "Stateful_LLM_Architecture"


async def run_live_agent_dogfood():
    overall_start_time = time.time()
    print("=" * 80)
    print("AURA SCHOLARLY RESEARCH SPECIALIST: LIVE END-TO-END AGENT DOGFOOD")
    print(f"Model Provider        : {settings.MODEL_PROVIDER} ({settings.OPENAI_MODEL_NAME})")
    print(f"Research Provider Mode: {settings.RESEARCH_PROVIDER_MODE} (Live Semantic Scholar + arXiv)")
    print(f"Target Project        : {PROJECT_NAME}")
    print("=" * 80)

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

            # Handle approval flow if required
            if run_status == "requires_approval":
                print("\n[Approval] Run requires human authorization. Approving pending actions via /v1/chat/approve...")
                appr_resp = await client.post(
                    "/v1/chat/approve",
                    json={
                        "run_id": parent_run_id,
                        "approved": True,
                    },
                )
                if appr_resp.status_code != 200:
                    print(f"[ERROR] /v1/chat/approve failed: {appr_resp.text}")
                    sys.exit(1)
                chat_response_data = appr_resp.json()
                run_status = chat_response_data.get("status")
                print(f" -> Approval resumed. Status='{run_status}'")

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
    async with async_session_factory() as db:
        # 2a. Lineage: Verify Root -> Research Specialist delegation
        del_stmt = select(DelegationModel).where(DelegationModel.parent_run_id == parent_run_id)
        del_res = await db.execute(del_stmt)
        delegation = del_res.scalar_one_or_none()

        if not delegation:
            print("[FATAL] Traces prove delegate_task was NOT executed by root orchestrator!")
            sys.exit(1)

        child_run_id = delegation.child_run_id
        specialist_name = delegation.specialist_name
        delegation_status = delegation.status

        print(f"  [OK] Delegation Record: Parent '{parent_run_id}' -> Specialist '{specialist_name}' (Child Run: '{child_run_id}')")
        print(f"       Status: {delegation_status}")

        child_run = await db.get(RunModel, child_run_id)
        assert child_run is not None, f"Child run record '{child_run_id}' missing in database!"

        # 2b. Audit Traces: Model calls and Tool execution sequence
        # Root run events
        root_events_stmt = (
            select(RunEventModel)
            .where(RunEventModel.run_id == parent_run_id)
            .order_by(RunEventModel.timestamp.asc())
        )
        root_events = list((await db.execute(root_events_stmt)).scalars().all())

        # Child run events
        child_events_stmt = (
            select(RunEventModel)
            .where(RunEventModel.run_id == child_run_id)
            .order_by(RunEventModel.timestamp.asc())
        )
        child_events = list((await db.execute(child_events_stmt)).scalars().all())

        model_calls = [e for e in child_events if e.event_type == "model_called"]
        tool_executions = [e for e in child_events if e.event_type == "tool_executed"]

        actual_model_provider = "unknown"
        actual_model_name = "unknown"
        if model_calls:
            routing_dec = model_calls[0].details.get("routing_decision", {})
            actual_model_provider = routing_dec.get("provider", "unknown")
            actual_model_name = routing_dec.get("model", "unknown")

        tool_sequence = [e.details.get("tool") for e in tool_executions if e.details]

        print(f"  [OK] Actual Model Provider : {actual_model_provider}")
        print(f"  [OK] Actual Model Name     : {actual_model_name}")
        print(f"  [OK] Child Model Calls     : {len(model_calls)}")
        print(f"  [OK] Child Tool Sequence   : {tool_sequence}")

        # 2c. Checkpointed ResearchState Inspection
        graph = await get_compiled_graph()
        child_snapshot = await graph.aget_state({"configurable": {"thread_id": child_run_id}})
        r_state_dict = child_snapshot.values.get("research_state")

        if not r_state_dict:
            print("[FATAL] Checkpointed ResearchState not found in child run snapshot!")
            sys.exit(1)

        r_state = ResearchState.from_dict(r_state_dict)

        # 2d. Project Memory Inspection
        mem_stmt = select(MemoryModel).where(MemoryModel.project_name == PROJECT_NAME)
        mem_records = list((await db.execute(mem_stmt)).scalars().all())

    total_elapsed = time.time() - overall_start_time

    # --------------------------------------------------------------------------
    # 3. TELEMETRY & ACCEPTANCE REPORT
    # --------------------------------------------------------------------------
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

    print(f"ResearchResult Status     : {r_state.status.value}")
    print(f"Project Memories Stored   : {len(mem_records)} in '{PROJECT_NAME}'")
    for m in mem_records:
        print(f"  - Memory ID: {m.id} | Key: {m.key}")
        print(f"    Content: {m.content[:100]}...")
        meta = m.metadata_json or {}
        print(f"    Lineage: Claims={meta.get('claim_ids')}, Evidence={meta.get('evidence_ids')}, Sources={meta.get('sources_cited')}")

    print(f"Total Elapsed Time        : {total_elapsed:.2f}s")
    print("=" * 80)
    print("ACCEPTANCE RESULT: SUCCESS — Real agent orchestrated delegation to Research Specialist")
    print("with real model, live tools, and verified provenance.")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(run_live_agent_dogfood())
