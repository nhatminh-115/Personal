"""Integration tests for controlled specialist delegation, scoped tools, and run lineage (Milestones 3C, 3D, 3E)."""

from pathlib import Path
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.errors import PermissionError, ToolError
from app.db.models import RunEventModel, RunModel
from app.delegation.registry import SpecialistRegistry, specialist_registry
from app.delegation.runtime import DelegationRuntime
from app.delegation.types import DelegationRequest, SpecialistDefinition
from app.tools.registry import tool_registry
from app.tools.scoped import ScopedToolRegistry


def test_scoped_tool_registry_enforces_whitelist_and_blocks_delegation():
    """Verify ScopedToolRegistry strictly restricts tools and always blocks delegate_task."""
    # Even if delegate_task is maliciously included in allowed_tools
    allowed = ["read_workspace_file", "delegate_task", "write_workspace_file"]
    scoped = ScopedToolRegistry(tool_registry, allowed)

    assert "delegate_task" not in scoped.allowed_tool_names
    assert "read_workspace_file" in scoped.allowed_tool_names
    assert "write_workspace_file" in scoped.allowed_tool_names

    # Check get
    assert scoped.get("read_workspace_file") is not None
    assert scoped.get("delegate_task") is None
    assert scoped.get("list_workspace_files") is None

    # Check get_tool_definitions
    tool_defs = scoped.get_tool_definitions()
    tool_def_names = [td.name for td in tool_defs]
    assert "delegate_task" not in tool_def_names
    assert "read_workspace_file" in tool_def_names

    # Attempt direct registration should fail
    with pytest.raises(ToolError, match="Cannot register new tools directly"):
        scoped.register(tool_registry.get("read_workspace_file"))


@pytest.mark.asyncio
async def test_specialist_cannot_delegate_to_another_specialist(test_db_session):
    """Verify specialists are strictly forbidden from delegating tasks to other specialists."""
    runtime = DelegationRuntime()
    req = DelegationRequest(
        specialist_name="coding",
        task_description="Recursively delegate to another agent",
        context={"is_specialist": True, "specialist_name": "malicious_subagent"},
        parent_run_id="parent-run-123",
        session_id="test-session-123",
    )

    with pytest.raises(PermissionError, match="cannot delegate to other specialists"):
        await runtime.delegate(req, db=test_db_session)


@pytest.mark.asyncio
async def test_root_orchestrator_delegates_to_coding_specialist_end_to_end(
    async_client: AsyncClient,
    test_db_session,
    setup_test_workspace: Path,
):
    """Verify full end-to-end flow:
    Personal Orchestrator receives request -> delegates to Coding Specialist ->
    Coding Specialist inspects, diagnoses, edits file, re-runs tests ->
    Returns result to Root Orchestrator -> Run lineage and audit trace recorded.
    """
    # 1. Setup workspace with initially buggy code
    code_file = setup_test_workspace / "calculator.py"
    code_file.write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")

    test_file = setup_test_workspace / "test_calculator.py"
    test_file.write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    # 2. Issue user request to Personal Orchestrator
    session_id = "sess-atlas-fix-1"
    response = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Fix the failing test in project Atlas",
            "project_name": "Atlas",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "waiting_for_approval"
    approval_id = data["approval_id"]
    assert approval_id is not None
    parent_run_id = data["run_id"]

    # 2b. Human Operator approves the file edit action
    dec_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize calculator.py bugfix"},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["status"] == "approved"
    assert dec_data["execution_status"] == "completed"
    assert "Personal Orchestrator" in dec_data["final_response"] or "calculator.py" in dec_data["final_response"]

    # 3. Verify Database Lineage: Parent Run & Child Run
    runs_res = await test_db_session.execute(
        select(RunModel).where(RunModel.session_id == session_id).order_by(RunModel.created_at.asc())
    )
    runs = list(runs_res.scalars().all())
    assert len(runs) >= 2

    parent_run = next((r for r in runs if r.id == parent_run_id), None)
    assert parent_run is not None
    assert parent_run.parent_run_id is None
    assert parent_run.status == "completed"

    child_run = next((r for r in runs if r.parent_run_id == parent_run_id), None)
    assert child_run is not None
    assert child_run.status == "completed"
    assert "[Specialist: coding]" in child_run.user_message
    assert "calculator.py" in child_run.final_response

    # 4. Verify Trace Events Lineage
    events_res = await test_db_session.execute(
        select(RunEventModel).where(RunEventModel.run_id == parent_run_id)
    )
    parent_events = [e.event_type for e in events_res.scalars().all()]
    assert "delegation_started" in parent_events
    assert "delegation_completed" in parent_events

    child_events_res = await test_db_session.execute(
        select(RunEventModel).where(RunEventModel.run_id == child_run.id)
    )
    child_events = [e.event_type for e in child_events_res.scalars().all()]
    assert "request_received" in child_events
    assert "step_completed" in child_events

    # 5. Verify Workspace mutation: file was actually updated
    updated_content = code_file.read_text(encoding="utf-8")
    assert "return a + b" in updated_content
    assert "+ 1" not in updated_content
