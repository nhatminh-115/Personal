"""Integration tests for Research Specialist delegation, scoped tools, and project memory (Phase 4)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import DelegationModel, MemoryModel, RunEventModel, RunModel
from app.delegation.registry import specialist_registry
from app.memory.base import MemoryType
from app.memory.service import SQLMemoryService
from app.tools.registry import tool_registry
from app.tools.scoped import ScopedToolRegistry


def test_research_specialist_tool_scoping_blocks_dangerous_tools():
    """Verify Research Specialist registry strictly disallows shell, sandbox, and delegate_task."""
    spec = specialist_registry.get("research")
    assert spec is not None

    scoped = ScopedToolRegistry(tool_registry, spec.allowed_tools)
    allowed_names = set(scoped.allowed_tool_names)

    # Allowed research tools
    assert "research_search" in allowed_names
    assert "read_document_section" in allowed_names
    assert "extract_evidence" in allowed_names
    assert "record_research_claim" in allowed_names
    assert "save_research_finding" in allowed_names
    assert "read_workspace_file" in allowed_names

    # Strictly forbidden tools
    assert "sandbox_shell_execute" not in allowed_names
    assert "sandbox_python_execute" not in allowed_names
    assert "write_workspace_file" not in allowed_names
    assert "delegate_task" not in allowed_names


@pytest.mark.asyncio
async def test_root_orchestrator_delegates_to_research_specialist_end_to_end(
    async_client: AsyncClient,
    test_db_session,
):
    """Verify full end-to-end flow:
    Personal Orchestrator receives prior art research query ->
    Delegates to Research Specialist ->
    Research Specialist performs 2 search iterations, reads Methods sections, extracts evidence,
    records claims, and saves durable finding to Project Memory ->
    Returns synthesis to Personal Orchestrator -> Run lineage and audit trace recorded.
    """
    session_id = "sess-research-atlas-1"
    response = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Investigate whether a proposed stateful LLM architecture has close prior work. Find the closest papers, inspect their methods, and explain the technical differences.",
            "project_name": "Atlas_Architecture",
        },
    )
    assert response.status_code == 200, f"Chat request failed: {response.text}"
    data = response.json()
    assert data["status"] == "completed"
    final_text = data.get("response", "")
    parent_run_id = data["run_id"]

    # 1. Verify synthesis contents
    assert "Chen & Davis" in final_text or "Stateful Multi-Turn" in final_text or "2308.1001" in final_text
    assert "Mendez & Rostova" in final_text or "Pipeline Checkpointing" in final_text or "2401.5502" in final_text
    assert "Exact Overlap" in final_text or "Exact Difference" in final_text or "Research Gap" in final_text

    # 2. Verify Database Lineage (Parent Run <-> Delegation <-> Child Run)
    del_stmt = select(DelegationModel).where(DelegationModel.parent_run_id == parent_run_id)
    del_res = await test_db_session.execute(del_stmt)
    delegation = del_res.scalar_one_or_none()
    assert delegation is not None, "Delegation record was not created!"
    assert delegation.specialist_name == "research"
    assert delegation.status == "completed"
    child_run_id = delegation.child_run_id

    # Verify Child Run
    child_run = await test_db_session.get(RunModel, child_run_id)
    assert child_run is not None
    assert child_run.parent_run_id == parent_run_id
    assert child_run.status == "completed"

    # 3. Verify Project Memory persistence
    mem_svc = SQLMemoryService(test_db_session)
    project_memories = await mem_svc.get_project_memories("Atlas_Architecture")
    assert len(project_memories) >= 1, "Expected research finding to be saved in project memory!"

    finding_memory = next((m for m in project_memories if "prior_art_stateful_execution" in m.key), None)
    assert finding_memory is not None
    assert "Prior art review" in finding_memory.content or "Chen & Davis" in finding_memory.content
    assert finding_memory.metadata_json.get("type") == "research_finding"
    assert len(finding_memory.metadata_json.get("source_references", [])) >= 2

    events_stmt = select(RunEventModel).where(RunEventModel.run_id == parent_run_id).order_by(RunEventModel.created_at)
    events = (await test_db_session.execute(events_stmt)).scalars().all()
    event_types = [e.event_type for e in events]
    assert "delegation_started" in event_types
    assert "delegation_completed" in event_types


@pytest.mark.asyncio
async def test_record_research_claim_rejects_nonexistent_evidence_id_in_production():
    """Integration test reproducing and preventing the bug: nonexistent placeholder
    evidence IDs like 'ev_extracted_1' must fail loudly in RecordResearchClaimTool
    and cannot be recorded into ResearchState.
    """
    from app.research.models import ResearchState
    from app.research.tools import RecordResearchClaimTool

    tool = RecordResearchClaimTool()
    # Context with empty evidence registry
    r_state = ResearchState()
    context = {"research_state": r_state.to_dict()}

    # Attempt to record factual claim with ungrounded placeholder ID
    res = await tool.execute(
        {
            "claim_text": "Chen & Davis uses ephemeral in-memory graphs.",
            "claim_type": "source_supported_fact",
            "evidence_ids": ["ev_extracted_1"],  # Fake placeholder ID
        },
        context=context,
    )

    assert res.success is False
    assert "Citation validation error" in res.error
    assert "references nonexistent evidence ID 'ev_extracted_1'" in res.error

    # Assert claim was NOT registered in research state
    updated_state = ResearchState.from_dict(context["research_state"])
    assert len(updated_state.claims) == 0


@pytest.mark.asyncio
async def test_save_research_finding_blocks_unsupported_gap_and_unverified_claims():
    """Integration test verifying SaveResearchFindingTool blocks overclaiming 'verified research gap'
    and blocks claims not present or unverified in ResearchState.
    """
    from app.research.models import ClaimType, EvidenceItem, ResearchClaim, ResearchSource, ResearchState, ResearchStatus
    from app.research.tools import SaveResearchFindingTool

    tool = SaveResearchFindingTool()
    source = ResearchSource(source_id="src_1", canonical_id="arxiv:1234", title="Paper 1")
    evidence = EvidenceItem(
        evidence_id="ev_valid_1",
        source_id="src_1",
        source_title="Paper 1",
        source_locator="Methods",
        extracted_text="Some text",
    )
    fact_claim = ResearchClaim(
        claim_id="cl_valid_1",
        claim_text="Paper 1 has some text",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_valid_1"],
        verification_status="verified",
    )
    r_state = ResearchState(
        sources={"src_1": source},
        evidence={"ev_valid_1": evidence},
        claims=[fact_claim],
        status=ResearchStatus.INSUFFICIENT_EVIDENCE,
    )
    context = {"research_state": r_state.to_dict()}

    # 1. Attempting to write overclaiming "verified research gap" when status is insufficient_evidence must fail
    res_overclaim = await tool.execute(
        {
            "project_name": "TestProject",
            "key": "finding_key",
            "claim_ids": ["cl_valid_1"],
            "finding_content": "We found a verified research gap in the literature.",
        },
        context=context,
    )
    assert res_overclaim.success is False
    assert "Finding asserts 'verified research gap'" in res_overclaim.error

    # 2. Attempting to cite nonexistent claim ID must fail
    res_missing_claim = await tool.execute(
        {
            "project_name": "TestProject",
            "key": "finding_key",
            "claim_ids": ["cl_nonexistent_999"],
            "finding_content": "Valid text",
        },
        context=context,
    )
    assert res_missing_claim.success is False
    assert "claim ID 'cl_nonexistent_999' not found" in res_missing_claim.error

    # 3. Valid write without overclaiming succeeds and stores claim_ids
    res_success = await tool.execute(
        {
            "project_name": "TestProject",
            "key": "finding_key",
            "claim_ids": ["cl_valid_1"],
            "finding_content": "Prior art review: Paper 1 describes in-memory states.",
        },
        context=context,
    )
    assert res_success.success is True
    assert "cl_valid_1" in res_success.metadata["claim_ids"]
    assert "ev_valid_1" in res_success.metadata["evidence_ids"]
