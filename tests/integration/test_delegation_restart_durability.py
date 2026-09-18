"""Integration tests for delegation restart durability and crash recovery (Milestone 3.1).

Verifies that:
1. When a delegated specialist run pauses for human approval, system restart preserves state.
2. Submitting approvals after process restart recovers LangGraph thread, unblocks parent graph,
   and completes the multi-turn specialist cycle with strict idempotency (no duplicate child runs).
3. Rejection after restart cleanly resolves the delegation without unhandled exceptions.
"""

from pathlib import Path
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.models import DelegationModel, RunEventModel, RunModel, RunStatus
from app.orchestrator.graph import close_checkpointer, init_checkpointer


@pytest.mark.asyncio
async def test_delegated_specialist_survives_restart_and_completes(
    async_client: AsyncClient,
    test_db_session,
    setup_test_workspace: Path,
    tmp_path: Path,
):
    """
    Verify delegated specialist execution across process restarts:
    1. Parent run delegates to coding specialist with persistent SQLite checkpointer.
    2. Coding specialist requests initial test run -> pauses for approval (Approval 1).
    3. Simulate system restart (close checkpointer, drop memory cache).
    4. Reconnect to DB/checkpointer and submit approvals 1, 2, and 3.
    5. Assert exactly 1 parent run, 1 child run, 1 delegation row, and correct trace lineage.
    """
    # 0. Setup durable SQLite checkpointer
    cp_file = tmp_path / "durability_checkpoints.db"
    await init_checkpointer(cp_file)

    # 1. Setup workspace with buggy code
    code_file = setup_test_workspace / "calculator.py"
    code_file.write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")

    test_file = setup_test_workspace / "test_calculator.py"
    test_file.write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    # 2. Trigger delegation
    session_id = "sess-durability-1"
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Fix the failing test in project Atlas",
            "project_name": "Atlas",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "waiting_for_approval"
    approval1_id = data["approval_id"]
    parent_run_id = data["run_id"]
    assert approval1_id is not None

    # 3. Simulate process restart / crash: close checkpointer connection pool
    await close_checkpointer()

    # Re-initialize checkpointer with the SAME persistent DB file
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # 4. Verify Approval 1 persisted in database
    app1_resp = await async_client.get(f"/v1/approvals/{approval1_id}")
    assert app1_resp.status_code == 200
    app1_data = app1_resp.json()
    assert app1_data["status"] == "pending"
    assert app1_data["tool_name"] == "sandbox_shell_execute"
    child_run_id = app1_data["run_id"]
    assert child_run_id != parent_run_id

    # 5. Submit Decision 1 (Authorize initial pytest)
    dec1_resp = await async_client.post(
        f"/v1/approvals/{approval1_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize initial pytest after restart"},
    )
    assert dec1_resp.status_code == 200
    dec1_data = dec1_resp.json()
    assert dec1_data["status"] == "approved"
    assert dec1_data["execution_status"] == "waiting_for_approval"
    approval2_id = dec1_data["approval_id"]
    assert approval2_id is not None
    assert approval2_id != approval1_id

    # Verify Approval 2 is for write_workspace_file
    app2_resp = await async_client.get(f"/v1/approvals/{approval2_id}")
    assert app2_resp.status_code == 200
    assert app2_resp.json()["tool_name"] == "write_workspace_file"

    # Simulate second restart before approval 2
    await close_checkpointer()
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # 6. Submit Decision 2 (Authorize write_workspace_file)
    dec2_resp = await async_client.post(
        f"/v1/approvals/{approval2_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize calculator bugfix"},
    )
    assert dec2_resp.status_code == 200
    dec2_data = dec2_resp.json()
    assert dec2_data["status"] == "approved"
    assert dec2_data["execution_status"] == "waiting_for_approval"
    approval3_id = dec2_data["approval_id"]
    assert approval3_id is not None
    assert approval3_id != approval2_id

    # Verify Approval 3 is for validation sandbox pytest
    app3_resp = await async_client.get(f"/v1/approvals/{approval3_id}")
    assert app3_resp.status_code == 200
    assert app3_resp.json()["tool_name"] == "sandbox_shell_execute"

    # 7. Submit Decision 3 (Authorize validation pytest)
    dec3_resp = await async_client.post(
        f"/v1/approvals/{approval3_id}/decision",
        json={"decision": "approved", "decision_notes": "Authorize verification pytest"},
    )
    assert dec3_resp.status_code == 200
    dec3_data = dec3_resp.json()
    assert dec3_data["status"] == "approved"
    assert dec3_data["execution_status"] == "completed"

    # 8. Verify Lineage in Database
    runs_res = await test_db_session.execute(
        select(RunModel).where(RunModel.session_id == session_id).order_by(RunModel.created_at.asc())
    )
    runs = list(runs_res.scalars().all())
    # Exactly one parent run and one child run
    assert len(runs) == 2

    parent_run = next((r for r in runs if r.id == parent_run_id), None)
    assert parent_run is not None
    assert parent_run.parent_run_id is None
    assert parent_run.status == "completed"

    child_run = next((r for r in runs if r.id == child_run_id), None)
    assert child_run is not None
    assert child_run.parent_run_id == parent_run_id
    assert child_run.status == "completed"

    # 9. Verify Exactly 1 Delegation Record with unique (parent_run_id, parent_tool_call_id)
    del_res = await test_db_session.execute(
        select(DelegationModel).where(DelegationModel.parent_run_id == parent_run_id)
    )
    delegations = list(del_res.scalars().all())
    assert len(delegations) == 1
    assert delegations[0].child_run_id == child_run_id
    assert delegations[0].status == "completed"

    # 10. Verify Event Lineage
    parent_events_res = await test_db_session.execute(
        select(RunEventModel).where(RunEventModel.run_id == parent_run_id)
    )
    parent_event_types = [e.event_type for e in parent_events_res.scalars().all()]
    assert parent_event_types.count("delegation_started") == 1
    assert parent_event_types.count("delegation_completed") == 1

    # 11. Verify workspace code was actually fixed
    updated_code = code_file.read_text(encoding="utf-8")
    assert "return a + b" in updated_code
    assert "+ 1" not in updated_code


@pytest.mark.asyncio
async def test_delegated_specialist_rejection_after_restart(
    async_client: AsyncClient,
    test_db_session,
    setup_test_workspace: Path,
    tmp_path: Path,
):
    """
    Verify rejection handling after process restart:
    1. Specialist pauses for approval.
    2. Process restarts.
    3. User rejects the pending approval.
    4. Run cleanly transitions to cancelled/failed without hanging or crashing.
    """
    cp_file = tmp_path / "reject_checkpoints.db"
    await init_checkpointer(cp_file)

    code_file = setup_test_workspace / "calculator.py"
    code_file.write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")

    test_file = setup_test_workspace / "test_calculator.py"
    test_file.write_text(
        "from calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )

    session_id = "sess-durability-reject-1"
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Fix the failing test in project Atlas",
            "project_name": "Atlas",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    approval_id = data["approval_id"]
    parent_run_id = data["run_id"]

    # Simulate process restart
    await close_checkpointer()
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # Submit Rejection
    dec_resp = await async_client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"decision": "rejected", "decision_notes": "Operator denied sandbox execution"},
    )
    assert dec_resp.status_code == 200
    dec_data = dec_resp.json()
    assert dec_data["status"] == "rejected"
    assert dec_data["execution_status"] in ("cancelled", "failed", "completed")

    # Verify run terminated cleanly in database
    runs_res = await test_db_session.execute(
        select(RunModel).where(RunModel.session_id == session_id)
    )
    runs = list(runs_res.scalars().all())
    assert len(runs) >= 1
    for r in runs:
        assert r.status in ("cancelled", "failed", "completed")
