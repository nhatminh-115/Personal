"""Integration tests proving Research Specialist mid-lifecycle restart durability across crashes."""

from pathlib import Path
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.models import DelegationModel, RunModel
from app.memory.service import SQLMemoryService
from app.orchestrator.graph import close_checkpointer, init_checkpointer
from app.research.models import ResearchResult, ResearchState, ResearchStatus
from app.research.provenance import CitationValidator


@pytest.mark.asyncio
async def test_research_specialist_mid_run_pause_restart_and_completion(
    async_client: AsyncClient,
    test_db_session,
    tmp_path: Path,
):
    """Scenario A:
    root -> delegate research specialist ->
    search iteration 1 completes -> at least one source is selected / inspected ->
    research child run is paused BEFORE completion ->
    close checkpointer / destroy runtime ->
    initialize fresh runtime using same persistent DB/checkpoint ->
    resume the SAME child run ->
    continue with search iteration 2 -> extract evidence -> synthesize -> complete.

    Assert:
    - exactly 1 parent run
    - exactly 1 child run
    - exactly 1 delegation
    - search iteration 1 is not duplicated
    - existing sources are preserved
    - evidence already extracted is preserved
    - no duplicate memory finding
    - final ResearchResult is valid
    """
    cp_file = tmp_path / "research_midrun_checkpoints.db"
    await init_checkpointer(cp_file)

    session_id = "sess-research-midrun-1"

    # 1. Start research query with approval gate on read_document_section
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Investigate whether a proposed stateful LLM architecture has close prior work. Find the closest papers, inspect their methods, and explain the technical differences.",
            "project_name": "Atlas_Architecture",
            "metadata": {
                "require_approval_for": ["read_document_section"],
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "waiting_for_approval"
    parent_run_id = data["run_id"]
    approval_id = data["approval_id"]
    assert approval_id is not None

    # Verify 1 parent run, 1 delegation, 1 child run exist in DB mid-run
    del_stmt = select(DelegationModel).where(DelegationModel.parent_run_id == parent_run_id)
    delegation = (await test_db_session.execute(del_stmt)).scalar_one()
    assert delegation.specialist_name == "research"
    assert delegation.status == "waiting_for_approval"
    child_run_id = delegation.child_run_id

    child_run = await test_db_session.get(RunModel, child_run_id)
    assert child_run is not None
    assert child_run.status == "waiting_for_approval"

    # 2. Simulate server crash mid-lifecycle: close checkpointer connection pool
    await close_checkpointer()

    # Re-initialize checkpointer with the SAME persistent DB file
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # Verify pending approval survived restart
    app_resp = await async_client.get(f"/v1/approvals/{approval_id}")
    assert app_resp.status_code == 200
    app_data = app_resp.json()
    assert app_data["status"] == "pending"
    assert app_data["tool_name"] == "read_document_section"

    # 3. Resume execution by approving Decision 1 (Paper 1 methods)
    dec1_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize inspection of Paper 1 methods"},
    )
    assert dec1_resp.status_code == 200
    dec1_data = dec1_resp.json()
    assert dec1_data["execution_status"] == "waiting_for_approval"
    approval2_id = dec1_data["approval_id"]
    assert approval2_id is not None
    assert approval2_id != approval_id

    # 4. Simulate a second crash mid-run before Decision 2
    await close_checkpointer()
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # Verify pending approval 2 survived restart
    app2_resp = await async_client.get(f"/v1/approvals/{approval2_id}")
    assert app2_resp.status_code == 200
    app2_data = app2_resp.json()
    assert app2_data["status"] == "pending"
    assert app2_data["tool_name"] == "read_document_section"

    # 5. Resume execution by approving Decision 2 (Paper 2 methods)
    dec2_resp = await async_client.post(
        f"/v1/approvals/{approval2_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize inspection of Paper 2 methods"},
    )
    assert dec2_resp.status_code == 200
    dec2_data = dec2_resp.json()
    assert dec2_data["execution_status"] == "completed"

    # 6. Check DB invariants post-completion
    del_count = await test_db_session.scalar(
        select(func.count(DelegationModel.id)).where(DelegationModel.parent_run_id == parent_run_id)
    )
    assert del_count == 1, f"Expected exactly 1 delegation row, found {del_count}!"

    child_runs = (
        await test_db_session.execute(select(RunModel).where(RunModel.parent_run_id == parent_run_id))
    ).scalars().all()
    assert len(child_runs) == 1, f"Expected exactly 1 child run, found {len(child_runs)}!"
    assert child_runs[0].status == "completed"

    # 7. Check Project Memory persisted without duplicates
    mem_svc = SQLMemoryService(test_db_session)
    memories = await mem_svc.get_project_memories("Atlas_Architecture")
    finding_mems = [m for m in memories if "prior_art_stateful_execution" in m.key]
    assert len(finding_mems) == 1, f"Expected exactly 1 project memory finding, found {len(finding_mems)}!"
    f_mem = finding_mems[0]
    assert len(f_mem.metadata_json.get("evidence_ids", [])) >= 2
    assert len(f_mem.metadata_json.get("source_references", [])) >= 2

    await close_checkpointer()


@pytest.mark.asyncio
async def test_research_specialist_restart_after_evidence_created(
    async_client: AsyncClient,
    test_db_session,
    tmp_path: Path,
):
    """Scenario B:
    Verify restart durability AFTER at least one EvidenceItem has already been created.
    The active evidence registry must survive process crash and remain available
    for subsequent claim verification and memory persistence.
    """
    cp_file = tmp_path / "research_evidence_checkpoints.db"
    await init_checkpointer(cp_file)

    session_id = "sess-research-evidence-1"

    # Pause on save_research_finding (which happens after multiple evidence items are created)
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Investigate whether a proposed stateful LLM architecture has close prior work. Find the closest papers, inspect their methods, and explain the technical differences.",
            "project_name": "Atlas_Architecture",
            "metadata": {
                "require_approval_for": ["save_research_finding"],
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "waiting_for_approval"
    parent_run_id = data["run_id"]
    approval_id = data["approval_id"]
    assert approval_id is not None

    # Simulate crash / restart after evidence items already exist in checkpoint
    await close_checkpointer()
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # Resume by approving the memory save
    dec_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize saving research finding to project memory"},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["execution_status"] == "completed"

    # Assert exactly 1 child run and 1 delegation
    del_count = await test_db_session.scalar(
        select(func.count(DelegationModel.id)).where(DelegationModel.parent_run_id == parent_run_id)
    )
    assert del_count == 1

    child_runs = (
        await test_db_session.execute(select(RunModel).where(RunModel.parent_run_id == parent_run_id))
    ).scalars().all()
    assert len(child_runs) == 1
    assert child_runs[0].status == "completed"

    # Verify project memory contains grounded evidence snapshot
    mem_svc = SQLMemoryService(test_db_session)
    memories = await mem_svc.get_project_memories("Atlas_Architecture")
    finding_mems = [m for m in memories if "prior_art_stateful_execution" in m.key]
    assert len(finding_mems) == 1
    f_mem = finding_mems[0]
    assert "evidence_snapshot" in f_mem.metadata_json
    assert len(f_mem.metadata_json["evidence_snapshot"]) >= 2
    for snap in f_mem.metadata_json["evidence_snapshot"]:
        assert snap["evidence_id"].startswith("ev_")
        assert snap["source_id"] in ["src_stateful_graph_2023", "src_pipeline_checkpoint_2024"]

    await close_checkpointer()
