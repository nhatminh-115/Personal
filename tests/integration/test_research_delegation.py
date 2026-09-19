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

    # 4. Verify Audit Trace Events
    events_stmt = select(RunEventModel).where(RunEventModel.run_id == parent_run_id).order_by(RunEventModel.created_at)
    events = (await test_db_session.execute(events_stmt)).scalars().all()
    event_types = [e.event_type for e in events]
    assert "delegation_started" in event_types
    assert "delegation_completed" in event_types
