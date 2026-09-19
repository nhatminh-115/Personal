"""Phase 4 Research Specialist Live Verification Script.

Exercises real FastAPI HTTP endpoints (/v1/chat) and core Phase 4 capabilities:
1. Canonical Source Deduplication & Normalized Title Identity.
2. Strict Citation Provenance & Evidence Invariants (rejects fake citations).
3. Production Vertical Slice:
   Personal Orchestrator delegates prior art analysis to Research Specialist:
   - 2 distinct search iterations
   - 3 candidate sources discovered, 1 rejected as irrelevant
   - 2 candidate sources inspected at Methods section
   - Evidence items extracted with locators
   - Claims recorded and verified
   - High-value finding persisted to project memory
   - Structured synthesis returned to Root Orchestrator
4. Database Lineage and Audit Trace verification.
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path
import httpx
from sqlalchemy import func, select

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

# Configure isolated verification database
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///aura_verify_p4.db"
os.environ["CHECKPOINT_DB_PATH"] = "./aura_verify_p4_checkpoints.db"
os.environ["MODEL_PROVIDER"] = "mock"

# Remove any previous verification artifacts
for p in ["aura_verify_p4.db", "aura_verify_p4_checkpoints.db"]:
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass

from app.api.server import create_app, lifespan
from app.core.settings import settings
from app.db.models import DelegationModel, MemoryModel, RunEventModel, RunModel
from app.db.session import async_session_factory
from app.delegation.registry import specialist_registry
from app.memory.service import SQLMemoryService
from app.orchestrator.graph import close_checkpointer, get_compiled_graph
from app.research.dedup import SourceDeduplicator, compute_canonical_id, normalize_title
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchSource,
    ResearchState,
    SourceStatus,
)
from app.research.provenance import (
    CitationValidationError,
    CitationValidator,
    validate_research_result,
    validate_research_state,
)


async def run_phase4_verification():
    print("=" * 80, flush=True)
    print("AURA PHASE 4 VERIFICATION: RESEARCH SPECIALIST & KNOWLEDGE-WORK PROVENANCE", flush=True)
    print("=" * 80, flush=True)

    app = create_app()
    verify_workspace = Path("./aura_verify_workspace_p4").resolve()
    if verify_workspace.exists():
        shutil.rmtree(verify_workspace)
    verify_workspace.mkdir(parents=True, exist_ok=True)

    original_ws = settings.AURA_WORKSPACE_ROOT
    settings.AURA_WORKSPACE_ROOT = verify_workspace

    try:
        # -------------------------------------------------------------
        # STEP 1: Canonical Source Deduplication & Identifier Invariants
        # -------------------------------------------------------------
        print("\n[Step 1] Verifying Canonical Source Deduplication & Merging...", flush=True)
        src_arxiv = ResearchSource(
            source_id="src_test_arxiv",
            canonical_id="arxiv:2308.1001",
            title="Stateful Multi-Turn Agent Workflows",
            authors=["Alice Chen"],
            year=2023,
            url="https://arxiv.org/abs/2308.1001",
            abstract="Initial brief abstract.",
            sections={"introduction": "Intro content."},
            status=SourceStatus.CANDIDATE,
        )
        src_mirror = ResearchSource(
            source_id="src_test_mirror",
            canonical_id="arxiv:2308.1001",
            title="Stateful Multi-Turn Agent Workflows: A Graph Approach",
            authors=["Alice Chen", "Bob Davis"],
            year=2023,
            url="https://semanticscholar.org/paper/stateful-workflows",
            abstract="Much richer and detailed abstract covering state transitions.",
            sections={"methods": "Detailed methods content."},
            status=SourceStatus.CANDIDATE,
        )

        existing_sources = {src_arxiv.source_id: src_arxiv}
        new_sources = SourceDeduplicator.deduplicate([src_mirror], existing_sources=existing_sources)

        assert len(new_sources) == 0, "Duplicate source was not merged!"
        merged = existing_sources[src_arxiv.source_id]
        assert "https://semanticscholar.org/paper/stateful-workflows" in merged.aliases
        assert "methods" in merged.sections
        assert "introduction" in merged.sections
        assert "Bob Davis" in merged.authors
        print(" -> Canonical deduplication verified: duplicate papers from mirrors merged into single identity.", flush=True)

        # -------------------------------------------------------------
        # STEP 2: Strict Citation Provenance & Evidence Invariants
        # -------------------------------------------------------------
        print("\n[Step 2] Verifying Citation Provenance & Anti-Hallucination Invariants...", flush=True)
        test_evidence = EvidenceItem(
            evidence_id="ev_valid_01",
            source_id="src_test_arxiv",
            source_title="Stateful Multi-Turn Agent Workflows",
            source_locator="Section: methods",
            extracted_text="Graph nodes reside in memory and do not implement persistent checkpoints.",
        )
        evidence_map = {"ev_valid_01": test_evidence}

        # Valid factual claim
        valid_claim = ResearchClaim(
            claim_id="cl_v1",
            claim_text="Paper 1 uses in-memory graph without persistent checkpoints.",
            claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
            evidence_ids=["ev_valid_01"],
        )
        ok, err = CitationValidator.validate_claim(valid_claim, evidence_map, existing_sources)
        assert ok is True and err is None

        # Fabricated / nonexistent citation must fail loudly
        fake_claim = ResearchClaim(
            claim_id="cl_fake",
            claim_text="Paper 1 supports Byzantine fault tolerance.",
            claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
            evidence_ids=["ev_nonexistent_fake_999"],
        )
        try:
            CitationValidator.validate_claim(fake_claim, evidence_map, existing_sources, strict=True)
            raise AssertionError("Expected CitationValidationError for fake citation ID!")
        except CitationValidationError as exc:
            assert "references nonexistent evidence ID" in str(exc)
            print(f" -> Provenance barrier verified: fake citation rejected loudly ({exc})", flush=True)

        # -------------------------------------------------------------
        # STEP 3: Production Vertical Slice via FastAPI /v1/chat
        # -------------------------------------------------------------
        print("\n[Step 3] Executing Real Research Specialist Vertical Slice via /v1/chat...", flush=True)
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=90.0) as client:
                session_id = "sess-p4-verify-live"
                chat_resp = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": session_id,
                        "message": "Investigate whether a proposed stateful LLM architecture has close prior work. Find the closest papers, inspect their methods, and explain the technical differences.",
                        "project_name": "Atlas_Architecture",
                    },
                )
                assert chat_resp.status_code == 200, f"Chat request failed: {chat_resp.text}"
                chat_data = chat_resp.json()
                assert chat_data["status"] == "completed"
                response_text = chat_data.get("response", "")
                parent_run_id = chat_data["run_id"]

                print("\n[Orchestrator Research Synthesis Output]:")
                print("-" * 60)
                print(response_text[:600] + "...\n[truncated for brevity]")
                print("-" * 60)

                # 3a. Assert technical content synthesis
                assert "Chen & Davis" in response_text or "Stateful Multi-Turn" in response_text or "2308.1001" in response_text
                assert "Mendez & Rostova" in response_text or "Pipeline Checkpointing" in response_text or "2401.5502" in response_text
                assert "Verified Factual Findings" in response_text
                assert "Identified Research Gap" in response_text
                assert "No evidence-backed research gap can be established from the current corpus." in response_text
                assert "No literature source demonstrates crash-resilient transactional execution" not in response_text
                assert "Prior art lacks combined durable checkpointing and human authorization gating" not in response_text
                print(" -> Technical comparison and synthesis validated: claims rendered strictly from validated findings without fabricated conclusions.", flush=True)

                # 3b. Verify Database Lineage & Durable ResearchState
                print("\n[Step 4] Verifying Database Lineage, Audit Trail & Authoritative ResearchState...", flush=True)
                async with async_session_factory() as db:
                    del_stmt = select(DelegationModel).where(DelegationModel.parent_run_id == parent_run_id)
                    del_res = await db.execute(del_stmt)
                    delegation = del_res.scalar_one_or_none()
                    assert delegation is not None
                    assert delegation.specialist_name == "research"
                    assert delegation.status == "completed"
                    child_run_id = delegation.child_run_id

                    child_run = await db.get(RunModel, child_run_id)
                    assert child_run is not None
                    assert child_run.parent_run_id == parent_run_id
                    assert child_run.status == "completed"
                    print(f" -> DB Lineage verified: Parent Run '{parent_run_id}' <-> Child Specialist Run '{child_run_id}'", flush=True)

                    # 3c. Inspect checkpointed ResearchState
                    graph = await get_compiled_graph()
                    child_snapshot = await graph.aget_state({"configurable": {"thread_id": child_run_id}})
                    r_state_dict = child_snapshot.values.get("research_state")
                    assert r_state_dict is not None, "ResearchState was not saved in LangGraph checkpoint!"
                    r_state = ResearchState.from_dict(r_state_dict)

                    # Assert >= 2 distinct ResearchQuery records
                    assert len(r_state.queries) >= 2, f"Expected >= 2 queries, found {len(r_state.queries)}"
                    assert len({q.query_text for q in r_state.queries}) >= 2
                    print(f" -> Multi-query execution verified: {len(r_state.queries)} distinct queries recorded.", flush=True)

                    # Assert >= 3 candidate sources discovered in canonical registry
                    assert len(r_state.sources) >= 3, f"Expected >= 3 sources, found {len(r_state.sources)}"
                    print(f" -> Canonical sources verified: {len(r_state.sources)} sources in shared registry.", flush=True)

                    # Assert >= 2 inspected sources
                    assert len(r_state.inspected_source_ids) >= 2
                    print(f" -> Inspected sources verified: {r_state.inspected_source_ids}", flush=True)

                    # Assert >= 1 rejected/unselected source
                    unselected = [s for s in r_state.sources.values() if s.source_id not in r_state.inspected_source_ids]
                    assert len(unselected) >= 1
                    print(f" -> Rejected/unselected distractor verified: {[s.source_id for s in unselected]}", flush=True)

                    # Assert >= 2 actual EvidenceItems with authoritative IDs
                    assert len(r_state.evidence) >= 2
                    actual_ev_ids = list(r_state.evidence.keys())
                    print(f" -> Authoritative dynamic evidence IDs: {actual_ev_ids}", flush=True)

                    # Explicitly assert that fake placeholder IDs like ev_extracted_1 do NOT exist
                    assert "ev_extracted_1" not in actual_ev_ids, "Fake placeholder ID 'ev_extracted_1' detected in registry!"
                    assert "ev_extracted_2" not in actual_ev_ids, "Fake placeholder ID 'ev_extracted_2' detected in registry!"

                    # Assert factual claims reference real EvidenceItems and each EvidenceItem references real Source
                    assert len(r_state.claims) >= 1
                    for claim in r_state.claims:
                        if claim.claim_type == ClaimType.SOURCE_SUPPORTED_FACT:
                            assert len(claim.evidence_ids) >= 1
                            for eid in claim.evidence_ids:
                                assert eid in r_state.evidence
                                assert eid != "ev_extracted_1"
                    for ev in r_state.evidence.values():
                        assert ev.source_id in r_state.sources
                        assert ev.metadata.get("grounded") is True

                    # 3d. Verify Project Memory persistence with exact claim and evidence IDs
                    mem_svc = SQLMemoryService(db)
                    project_memories = await mem_svc.get_project_memories("Atlas_Architecture")
                    assert len(project_memories) >= 1, "Expected research finding to be stored in project memory!"
                    finding = next((m for m in project_memories if "prior_art_stateful_execution" in m.key), None)
                    assert finding is not None
                    assert "Prior art review" in finding.content or "Chen & Davis" in finding.content
                    assert "verified research gap" not in finding.content.lower()
                    assert finding.metadata_json.get("type") == "research_finding"
                    assert len(finding.metadata_json.get("source_references", [])) >= 2
                    finding_ev_ids = finding.metadata_json.get("evidence_ids", [])
                    assert len(finding_ev_ids) >= 2
                    for feid in finding_ev_ids:
                        assert feid in actual_ev_ids, f"Project memory contains unknown evidence ID '{feid}'!"
                        assert feid != "ev_extracted_1"
                    finding_claim_ids = finding.metadata_json.get("claim_ids", [])
                    assert len(finding_claim_ids) >= 1
                    print(f" -> Project Memory verified: '{finding.key}' persisted with claim IDs: {finding_claim_ids} and evidence IDs: {finding_ev_ids}", flush=True)

                    # Assert final ResearchResult passes canonical validate_research_state helper
                    val_res = validate_research_state(r_state, strict=True)
                    assert val_res["is_valid"] is True
                    assert val_res["unsupported_count"] == 0
                    assert val_res["verified_facts_count"] >= 1
                    survived_claim = val_res["verified_facts"][0]
                    assert survived_claim.claim_id.startswith("cl_")
                    assert survived_claim.claim_id in finding_claim_ids
                    for eid in survived_claim.evidence_ids:
                        assert eid in r_state.evidence
                        assert r_state.evidence[eid].source_id in r_state.sources
                    print(f" -> Final ResearchResult passed validate_research_state with {val_res['verified_facts_count']} verified factual claims and 0 unsupported claims.", flush=True)

                    # Tag and output fixture note
                    for src in r_state.sources.values():
                        assert src.metadata.get("fixture") is True
                    print(" -> Deterministic research fixture verification: All sources correctly labeled with metadata['fixture'] = True.", flush=True)

                    # 3e. Verify Audit Events
                    ev_stmt = select(RunEventModel).where(RunEventModel.run_id == parent_run_id).order_by(RunEventModel.created_at)
                    events = (await db.execute(ev_stmt)).scalars().all()
                    ev_types = [e.event_type for e in events]
                    assert "delegation_started" in ev_types
                    assert "delegation_completed" in ev_types
                    print(f" -> Audit Trail verified: {len(events)} events recorded for parent run.", flush=True)

        print("\n" + "=" * 80)
        print("PHASE 4 VERIFICATION PASSED: ALL RESEARCH CAPABILITIES ACCEPTED SUCCESSFULLY")
        print("=" * 80, flush=True)

    finally:
        await close_checkpointer()
        settings.AURA_WORKSPACE_ROOT = original_ws
        if verify_workspace.exists():
            shutil.rmtree(verify_workspace, ignore_errors=True)
        for p in ["aura_verify_p4.db", "aura_verify_p4_checkpoints.db"]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(run_phase4_verification(), timeout=120.0))
