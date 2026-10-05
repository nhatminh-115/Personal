"""Cooperative cancellation checks shared by root and specialist executions."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.db.models import RunModel, RunStatus, SessionModel
from app.orchestrator.nodes import _cancellation_result, execute_tool_node, reason_node


@pytest.mark.asyncio
async def test_cancelled_root_stops_specialist_before_tool_execution(test_db_session):
    test_db_session.add(SessionModel(id="cancel-root-session"))
    test_db_session.add_all([
        RunModel(
            id="cancel-root-run",
            session_id="cancel-root-session",
            status=RunStatus.RUNNING.value,
            user_message="parent",
            cancel_requested_at=datetime.now(timezone.utc),
        ),
        RunModel(
            id="cancel-child-run",
            session_id="cancel-root-session",
            parent_run_id="cancel-root-run",
            status=RunStatus.RUNNING.value,
            user_message="child",
        ),
    ])
    await test_db_session.commit()

    tool = type("Tool", (), {"execute": AsyncMock()})()
    registry = type("Registry", (), {"get": lambda _self, _name: tool})()
    state = {
        "run_id": "cancel-child-run",
        "session_id": "cancel-root-session",
        "tool_requests": [{"id": "tool-call-1", "name": "workspace.read", "arguments": {}}],
        "tool_approvals": {},
        "messages": [],
        "errors": [],
    }

    result = await execute_tool_node(state, {"configurable": {"db": test_db_session, "tool_registry": registry}})

    assert result["execution_status"] == RunStatus.CANCELLED.value
    assert result["tool_requests"] == []
    tool.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_without_cancel_marker_continues(test_db_session):
    test_db_session.add_all([
        SessionModel(id="not-cancelled-session"),
        RunModel(
            id="not-cancelled-run",
            session_id="not-cancelled-session",
            status=RunStatus.RUNNING.value,
            user_message="continue",
        ),
    ])
    await test_db_session.commit()

    assert await _cancellation_result(
        {"run_id": "not-cancelled-run"},
        {"db": test_db_session},
    ) is None


@pytest.mark.asyncio
async def test_cancelled_run_does_not_start_a_model_call(test_db_session):
    test_db_session.add_all([
        SessionModel(id="cancel-before-model-session"),
        RunModel(
            id="cancel-before-model-run",
            session_id="cancel-before-model-session",
            status=RunStatus.RUNNING.value,
            user_message="do not invoke model",
            cancel_requested_at=datetime.now(timezone.utc),
        ),
    ])
    await test_db_session.commit()
    model_router = type("ModelRouter", (), {"route": AsyncMock()})()

    result = await reason_node(
        {"run_id": "cancel-before-model-run", "session_id": "cancel-before-model-session"},
        {"configurable": {"db": test_db_session, "model_router": model_router}},
    )

    assert result["execution_status"] == RunStatus.CANCELLED.value
    model_router.route.assert_not_awaited()
