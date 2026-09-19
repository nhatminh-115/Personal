"""Integration test proving database-enforced, race-safe Delegation idempotency under concurrency."""

import asyncio
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import DelegationModel, RunEventModel, RunModel, RunStatus
from app.delegation.registry import SpecialistRegistry
from app.delegation.runtime import DelegationRuntime
from app.delegation.types import DelegationRequest, SpecialistDefinition
from app.observability.tracer import TraceService


@pytest.fixture
def delegation_db_engine():
    """Create a temporary SQLite database with current schema for concurrency testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    async_url = f"sqlite+aiosqlite:///{db_path.replace(chr(92), '/')}"
    engine = create_async_engine(async_url, echo=False)

    yield engine, db_path

    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_concurrent_delegation_creation_idempotency(delegation_db_engine, monkeypatch):
    """Prove that concurrent callers delegating the exact same (parent_run_id, parent_tool_call_id)
    resolve deterministically to exactly one child run without orphan runs or duplicate delegations.
    """
    engine, db_path = delegation_db_engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Seed parent run in DB
    parent_run_id = f"parent-run-{uuid.uuid4().hex[:8]}"
    session_id = f"session-{uuid.uuid4().hex[:8]}"
    parent_tool_call_id = f"call-{uuid.uuid4().hex[:8]}"

    async with session_maker() as session:
        parent_run = RunModel(
            id=parent_run_id,
            session_id=session_id,
            user_message="Initial orchestrator user request",
            status=RunStatus.RUNNING.value,
        )
        session.add(parent_run)
        await session.commit()

    # 2. Setup custom specialist registry
    registry = SpecialistRegistry()
    registry.register(
        SpecialistDefinition(
            name="concurrency_coder",
            description="Specialist for testing delegation concurrency",
            system_prompt_template="You are a concurrency testing coder.",
            allowed_tools=["read_workspace_file"],
        )
    )
    runtime = DelegationRuntime(registry=registry)

    # 3. Mock graph execution cleanly via monkeypatch outside workers
    mock_graph = AsyncMock()
    mock_snapshot = MagicMock()
    mock_snapshot.next = None
    mock_snapshot.values = {
        "execution_status": "completed",
        "final_response": "Child specialist execution completed successfully",
        "step_number": 2,
    }
    mock_graph.aget_state.return_value = mock_snapshot

    async def fake_ainvoke(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {
            "execution_status": "completed",
            "final_response": "Child specialist execution completed successfully",
            "step_number": 2,
        }

    mock_graph.ainvoke = AsyncMock(side_effect=fake_ainvoke)
    monkeypatch.setattr("app.delegation.runtime.get_compiled_graph", AsyncMock(return_value=mock_graph))

    num_concurrent_callers = 8

    async def call_delegate(caller_idx: int):
        async with session_maker() as session:
            trace_service = TraceService(session)
            req = DelegationRequest(
                specialist_name="concurrency_coder",
                task_description=f"Run concurrent coding task from caller {caller_idx}",
                parent_run_id=parent_run_id,
                parent_tool_call_id=parent_tool_call_id,
                session_id=session_id,
            )
            result = await runtime.delegate(
                request=req,
                db=session,
                services={"trace_service": trace_service},
            )
            return result

    # 4. Launch all concurrent calls simultaneously
    tasks = [call_delegate(i) for i in range(num_concurrent_callers)]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    assert len(results) == num_concurrent_callers

    # 5. Assert all callers resolved to the EXACT SAME child_run_id
    winning_child_run_id = results[0].child_run_id
    assert winning_child_run_id is not None
    for res in results:
        assert res.child_run_id == winning_child_run_id, (
            f"Caller resolved to different child_run_id: {res.child_run_id} vs {winning_child_run_id}"
        )
        assert res.status in (RunStatus.RUNNING.value, RunStatus.COMPLETED.value)

    # 6. Verify Database Invariants
    async with session_maker() as session:
        # Exactly 1 delegation record exists for (parent_run_id, parent_tool_call_id)
        del_count_stmt = select(func.count(DelegationModel.id)).where(
            DelegationModel.parent_run_id == parent_run_id,
            DelegationModel.parent_tool_call_id == parent_tool_call_id,
        )
        del_count = await session.scalar(del_count_stmt)
        assert del_count == 1, f"Expected exactly 1 DelegationModel row, found {del_count}!"

        # Exactly 1 child RunModel exists with parent_run_id
        child_runs_stmt = select(RunModel).where(RunModel.parent_run_id == parent_run_id)
        child_runs = (await session.execute(child_runs_stmt)).scalars().all()
        assert len(child_runs) == 1, (
            f"Expected exactly 1 child RunModel (no orphan runs from losing races), found {len(child_runs)}!"
        )
        assert child_runs[0].id == winning_child_run_id

        # Trace events: delegation_started recorded exactly once for parent_run_id
        started_events_stmt = select(RunEventModel).where(
            RunEventModel.run_id == parent_run_id,
            RunEventModel.event_type == "delegation_started",
        )
        started_events = (await session.execute(started_events_stmt)).scalars().all()
        assert len(started_events) == 1, (
            f"Expected exactly 1 'delegation_started' event, found {len(started_events)}!"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_null_parent_tool_call_id_allows_multiple_delegations(delegation_db_engine):
    """Prove that null parent_tool_call_id (partial index condition) allows multiple distinct
    delegation rows for the same parent_run without constraint violation.
    """
    engine, db_path = delegation_db_engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    parent_run_id = f"parent-null-{uuid.uuid4().hex[:8]}"
    session_id = f"session-null-{uuid.uuid4().hex[:8]}"

    async with session_maker() as session:
        session.add(RunModel(id=parent_run_id, session_id=session_id, user_message="parent run"))
        await session.commit()

        # Insert 3 delegations with parent_tool_call_id=None
        for i in range(3):
            child_id = f"child-{i}-{uuid.uuid4().hex[:6]}"
            session.add(RunModel(id=child_id, session_id=session_id, user_message=f"child run {i}"))
            del_rec = DelegationModel(
                parent_run_id=parent_run_id,
                parent_tool_call_id=None,
                child_run_id=child_id,
                specialist_name="concurrency_coder",
                status=RunStatus.COMPLETED.value,
            )
            session.add(del_rec)
        await session.commit()

        count_stmt = select(func.count(DelegationModel.id)).where(
            DelegationModel.parent_run_id == parent_run_id,
            DelegationModel.parent_tool_call_id.is_(None),
        )
        count = await session.scalar(count_stmt)
        assert count == 3

    await engine.dispose()
