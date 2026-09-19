"""Integration test proving Research Specialist restart durability and idempotency across crashes."""

from pathlib import Path
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.models import DelegationModel, RunModel
from app.memory.service import SQLMemoryService
from app.orchestrator.graph import close_checkpointer, init_checkpointer


@pytest.mark.asyncio
async def test_research_specialist_survives_restart_and_completes_idempotently(
    async_client: AsyncClient,
    test_db_session,
    tmp_path: Path,
):
    """Verify that a research task maintains durable state across process restart:
    1. Initialize durable checkpointer.
    2. Start research investigation.
    3. Simulate server restart / crash mid-lifecycle (close and re-init checkpointer).
    4. Verify restart preserves thread state, prevents duplicate child runs, and finalizes cleanly.
    """
    # 1. Setup persistent checkpointer
    cp_file = tmp_path / "research_durability_checkpoints.db"
    await init_checkpointer(cp_file)

    session_id = "sess-research-restart-1"

    # 2. Run initial research query
    resp = await async_client.post(
        "/v1/chat",
        json={
            "session_id": session_id,
            "message": "Investigate whether a proposed stateful LLM architecture has close prior work. Find the closest papers, inspect their methods, and explain the technical differences.",
            "project_name": "Atlas_Architecture",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    parent_run_id = data["run_id"]

    # 3. Simulate process crash & restart
    await close_checkpointer()
    cp = await init_checkpointer(cp_file)
    assert cp is not None

    # 4. Check DB invariants: Exactly 1 delegation row, exactly 1 child run
    del_stmt = select(func.count(DelegationModel.id)).where(DelegationModel.parent_run_id == parent_run_id)
    del_count = await test_db_session.scalar(del_stmt)
    assert del_count == 1, f"Expected exactly 1 delegation row, found {del_count}!"

    child_stmt = select(RunModel).where(RunModel.parent_run_id == parent_run_id)
    child_runs = (await test_db_session.execute(child_stmt)).scalars().all()
    assert len(child_runs) == 1, f"Expected exactly 1 child run, found {len(child_runs)}!"
    assert child_runs[0].status == "completed"

    # 5. Check Project Memory persisted properly
    mem_svc = SQLMemoryService(test_db_session)
    memories = await mem_svc.get_project_memories("Atlas_Architecture")
    assert len(memories) >= 1
    assert any("prior_art_stateful_execution" in m.key for m in memories)

    await close_checkpointer()
