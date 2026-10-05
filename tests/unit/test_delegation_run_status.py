from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from sqlalchemy import select

from app.db.models import DelegationModel, RunModel, RunStatus, SessionModel
from app.delegation.runtime import DelegationRuntime
from app.delegation.types import DelegationRequest
from app.research.models import ResearchGoal, ResearchState


@pytest.mark.parametrize("terminal_status", [RunStatus.FAILED.value, RunStatus.CANCELLED.value])
@pytest.mark.asyncio
async def test_terminal_research_child_with_partial_state_keeps_its_status(test_db_session, monkeypatch, terminal_status):
    session_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id))
    test_db_session.add(RunModel(id=parent_run_id, session_id=session_id, user_message="Research this topic"))
    await test_db_session.commit()

    partial_research_state = ResearchState(
        goal=ResearchGoal(goal_id="goal-partial", user_query="Research this topic"),
    ).to_dict()
    graph = AsyncMock()
    graph.aget_state.return_value = MagicMock(next=None, values={})
    graph.ainvoke.return_value = {
        "execution_status": terminal_status,
        "final_response": f"Research specialist {terminal_status}.",
        "error_message": "provider request failed",
        "research_state": partial_research_state,
    }
    monkeypatch.setattr("app.delegation.runtime.get_compiled_graph", AsyncMock(return_value=graph))

    result = await DelegationRuntime().delegate(
        DelegationRequest(
            specialist_name="research",
            task_description="Research this topic",
            parent_run_id=parent_run_id,
            session_id=session_id,
        ),
        db=test_db_session,
        services={"research_provider": object(), "trace_service": AsyncMock()},
    )

    child = await test_db_session.get(RunModel, result.child_run_id)
    delegation = await test_db_session.scalar(
        select(DelegationModel).where(DelegationModel.child_run_id == result.child_run_id)
    )
    assert result.status == terminal_status
    assert result.artifacts["research_state"] == partial_research_state
    assert child is not None and child.status == terminal_status
    assert delegation is not None and delegation.status == terminal_status
    assert child.error_message == "provider request failed"
