"""Durable ask-before-cloud confirmation lifecycle tests."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.errors import RoutingConfirmationRequired
from app.db.models import RunModel, RoutingConfirmationModel, SessionModel
from app.models.base import ModelResponse, ToolCallRequest
from app.models.routing_policy import ModelSelection
from app.models.router import model_router


@pytest.mark.asyncio
async def test_approved_routing_confirmation_resumes_same_run(async_client, test_db_session, monkeypatch):
    mock_provider = model_router.get_provider("mock")
    selections = []

    def select_model(context):
        selections.append(context.explicit_model_override if context else None)
        if not context or not context.explicit_model_override:
            raise RoutingConfirmationRequired(
                "Cloud fallback requires confirmation.",
                {"proposed_provider": "openai", "proposed_model": "gpt-4o-mini"},
            )
        # Use the deterministic mock adapter while preserving the exact proposed
        # route in the persisted routing selection; no external model is called.
        return mock_provider, ModelSelection(
            provider_name="mock",
            model_name="mock-default",
            reason=f"confirmed route {context.explicit_model_override}",
        )

    monkeypatch.setattr(model_router, "select_model_for_task", select_model)
    started = await async_client.post(
        "/v1/chat",
        json={"session_id": "routing-confirm-approve", "message": "Summarize this test."},
    )

    assert started.status_code == 200
    started_data = started.json()
    assert started_data["status"] == "waiting_for_routing_confirmation"
    assert started_data["routing_confirmation_id"]
    assert mock_provider.call_history == []

    confirmation = await test_db_session.get(
        RoutingConfirmationModel, started_data["routing_confirmation_id"]
    )
    assert confirmation is not None
    assert confirmation.status == "pending"
    assert confirmation.proposed_provider == "openai"
    assert confirmation.proposed_model == "gpt-4o-mini"

    pending = await async_client.get("/v1/routing-confirmations/pending")
    assert pending.status_code == 200
    assert [row["id"] for row in pending.json()] == [confirmation.id]

    resumed = await async_client.post(
        f"/v1/routing-confirmations/{confirmation.id}/decision",
        json={"decision": "approved"},
    )
    assert resumed.status_code == 200
    resumed_data = resumed.json()
    assert resumed_data["status"] == "approved"
    assert resumed_data["execution_status"] == "completed"
    assert resumed_data["final_response"]
    assert mock_provider.call_history
    assert selections[-1] == "openai:gpt-4o-mini"

    run = await test_db_session.get(RunModel, started_data["run_id"])
    assert run.status == "completed"
    assert run.final_response == resumed_data["final_response"]

    retry = await async_client.post(
        f"/v1/routing-confirmations/{confirmation.id}/decision",
        json={"decision": "approved"},
    )
    assert retry.status_code == 200
    assert retry.json()["final_response"] == resumed_data["final_response"]


@pytest.mark.asyncio
async def test_rejected_routing_confirmation_never_calls_model(async_client, test_db_session, monkeypatch):
    mock_provider = model_router.get_provider("mock")

    def require_confirmation(_context):
        raise RoutingConfirmationRequired(
            "Cloud fallback requires confirmation.",
            {"proposed_provider": "openai", "proposed_model": "gpt-4o-mini"},
        )

    monkeypatch.setattr(model_router, "select_model_for_task", require_confirmation)
    started = await async_client.post(
        "/v1/chat",
        json={"session_id": "routing-confirm-reject", "message": "Do not run this."},
    )

    assert started.status_code == 200
    data = started.json()
    assert data["status"] == "waiting_for_routing_confirmation"
    assert mock_provider.call_history == []

    rejected = await async_client.post(
        f"/v1/routing-confirmations/{data['routing_confirmation_id']}/decision",
        json={"decision": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["execution_status"] == "cancelled"
    assert mock_provider.call_history == []

    run = await test_db_session.get(RunModel, data["run_id"])
    assert run.status == "cancelled"
    assert run.final_response


@pytest.mark.asyncio
async def test_pending_routing_confirmations_use_cursor_pages_and_session_filter(async_client, test_db_session):
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    confirmation_ids = []
    session_ids = []
    for index in range(5):
        session_id = f"pending-session-{index}"
        run_id = str(index + 1).zfill(36)
        confirmation_id = str(index + 101).zfill(36)
        session_ids.append(session_id)
        confirmation_ids.append(confirmation_id)
        test_db_session.add(SessionModel(id=session_id, title="Pending confirmation"))
        test_db_session.add(RunModel(id=run_id, session_id=session_id, user_message=f"message {index}"))
        test_db_session.add(RoutingConfirmationModel(
            id=confirmation_id,
            root_run_id=run_id,
            execution_run_id=run_id,
            session_id=session_id,
            proposed_provider="cloud",
            proposed_model=f"model-{index}",
            created_at=base_time + timedelta(seconds=index),
        ))
    await test_db_session.commit()

    first_response = await async_client.get("/v1/routing-confirmations/pending", params={"page_size": 2})
    assert first_response.status_code == 200
    first_page = first_response.json()
    assert [item["id"] for item in first_page] == confirmation_ids[:2]
    cursor = first_response.headers.get("X-Next-Cursor")
    assert cursor

    second_response = await async_client.get(
        "/v1/routing-confirmations/pending", params={"page_size": 2, "cursor": cursor},
    )
    assert second_response.status_code == 200
    assert [item["id"] for item in second_response.json()] == confirmation_ids[2:4]
    assert set(confirmation_ids[:2]).isdisjoint(item["id"] for item in second_response.json())

    filtered = await async_client.get(
        "/v1/routing-confirmations/pending", params={"session_id": session_ids[-1]},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [confirmation_ids[-1]]


@pytest.mark.asyncio
async def test_specialist_routing_confirmation_bubbles_to_root_and_resumes_child(
    async_client, test_db_session, monkeypatch
):
    mock_provider = model_router.get_provider("mock")
    mock_provider.queue_response(ModelResponse(
        content="Delegating to the coding specialist.",
        tool_calls=[ToolCallRequest(
            id="delegate-routing-confirmation",
            name="delegate_task",
            arguments={
                "specialist_name": "coding",
                "task_description": "Review the code and return a short summary.",
            },
        )],
    ))
    mock_provider.queue_response(ModelResponse(content="Child specialist completed after confirmation."))

    selected_contexts = []
    root_run_id = None

    # Keep the root on the standard mock route; only the distinct child run
    # requests cloud confirmation, then resume through the mock adapter.
    original_select = model_router.select_model_for_task

    def select_model(context):
        nonlocal root_run_id
        selected_contexts.append(context)
        if context and root_run_id is None:
            root_run_id = context.run_id
        if (
            context
            and context.run_id != root_run_id
            and not context.explicit_model_override
        ):
            raise RoutingConfirmationRequired(
                "Cloud fallback requires confirmation.",
                {"proposed_provider": "openai", "proposed_model": "gpt-4o-mini"},
            )
        if context and context.explicit_model_override:
            return mock_provider, ModelSelection(
                provider_name="mock",
                model_name="mock-default",
                reason=f"confirmed route {context.explicit_model_override}",
            )
        return original_select(context)

    monkeypatch.setattr(model_router, "select_model_for_task", select_model)
    started = await async_client.post(
        "/v1/chat",
        json={"session_id": "routing-confirm-child", "message": "Delegate a code review."},
    )

    assert started.status_code == 200
    data = started.json()
    assert data["status"] == "waiting_for_routing_confirmation", data
    assert mock_provider.call_history and len(mock_provider.call_history) == 1

    confirmation = await test_db_session.get(
        RoutingConfirmationModel, data["routing_confirmation_id"]
    )
    assert confirmation.root_run_id == data["run_id"]
    assert confirmation.execution_run_id != confirmation.root_run_id
    child_run = await test_db_session.get(RunModel, confirmation.execution_run_id)
    assert child_run.status == "waiting_for_routing_confirmation"

    resumed = await async_client.post(
        f"/v1/routing-confirmations/{confirmation.id}/decision",
        json={"decision": "approved"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["execution_status"] == "completed"
    assert mock_provider.call_history and len(mock_provider.call_history) >= 3
    assert any(
        context and context.explicit_model_override == "openai:gpt-4o-mini"
        for context in selected_contexts
    )

    parent_run = await test_db_session.get(RunModel, data["run_id"])
    child_run = await test_db_session.get(RunModel, confirmation.execution_run_id)
    assert parent_run.status == "completed"
    assert child_run.status == "completed"


@pytest.mark.asyncio
async def test_rejected_specialist_routing_confirmation_cancels_child_without_cloud_call(
    async_client, test_db_session, monkeypatch
):
    mock_provider = model_router.get_provider("mock")
    mock_provider.queue_response(ModelResponse(
        content="Delegate this review.",
        tool_calls=[ToolCallRequest(
            id="delegate-rejected-routing-confirmation",
            name="delegate_task",
            arguments={
                "specialist_name": "coding",
                "task_description": "Review the code.",
            },
        )],
    ))
    mock_provider.queue_response(ModelResponse(content="The specialist route was declined."))

    selected_contexts = []
    root_run_id = None

    def require_child_confirmation(context):
        nonlocal root_run_id
        selected_contexts.append(context)
        if context and root_run_id is None:
            root_run_id = context.run_id
        if context and context.run_id != root_run_id and not context.explicit_model_override:
            raise RoutingConfirmationRequired(
                "Cloud fallback requires confirmation.",
                {"proposed_provider": "openai", "proposed_model": "gpt-4o-mini"},
            )
        if context and context.explicit_model_override:
            return mock_provider, ModelSelection(
                provider_name="mock",
                model_name="mock-default",
                reason=f"confirmed route {context.explicit_model_override}",
            )
        return model_router.get_provider("mock"), ModelSelection(
            provider_name="mock",
            model_name="mock-default",
            reason="deterministic root mock",
        )

    monkeypatch.setattr(model_router, "select_model_for_task", require_child_confirmation)
    started = await async_client.post(
        "/v1/chat",
        json={"session_id": "routing-confirm-child-reject", "message": "Delegate a code review."},
    )

    assert started.status_code == 200
    data = started.json()
    assert data["status"] == "waiting_for_routing_confirmation"
    assert len(mock_provider.call_history) == 1

    confirmation = await test_db_session.get(
        RoutingConfirmationModel, data["routing_confirmation_id"]
    )
    child_run = await test_db_session.get(RunModel, confirmation.execution_run_id)
    assert child_run.status == "waiting_for_routing_confirmation"

    rejected = await async_client.post(
        f"/v1/routing-confirmations/{confirmation.id}/decision",
        json={"decision": "rejected"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["execution_status"] == "completed"
    assert len(mock_provider.call_history) == 2
    assert not any(
        context and context.explicit_model_override == "openai:gpt-4o-mini"
        for context in selected_contexts
    )

    parent_run = await test_db_session.get(RunModel, data["run_id"])
    child_run = await test_db_session.get(RunModel, confirmation.execution_run_id)
    assert parent_run.status == "completed"
    assert child_run.status == "cancelled"


@pytest.mark.parametrize(
    ("specialist_name", "overrides", "expected_model", "expected_reasoning_policy", "expected_reasoning_effort", "expected_lock"),
    [
        ("research", {"reasoning_override": "high"}, None, "fixed", "high", False),
        ("coding", {"model_override": "mock:mock-default"}, "mock:mock-default", "adaptive", "medium", True),
        (
            "coding",
            {"model_override": "mock:mock-default", "reasoning_override": "high"},
            "mock:mock-default",
            "fixed",
            "high",
            True,
        ),
    ],
)
@pytest.mark.asyncio
async def test_temporary_routing_overrides_propagate_to_specialist_snapshot(
    async_client,
    test_db_session,
    monkeypatch,
    specialist_name,
    overrides,
    expected_model,
    expected_reasoning_policy,
    expected_reasoning_effort,
    expected_lock,
):
    """Temporary root controls reach a child without replacing its route policy."""
    mock_provider = model_router.get_provider("mock")
    mock_provider.queue_response(ModelResponse(
        content="Delegate the task.",
        tool_calls=[ToolCallRequest(
            id=f"delegate-routing-propagation-{specialist_name}",
            name="delegate_task",
            arguments={
                "specialist_name": specialist_name,
                "task_description": "Return a concise deterministic summary.",
            },
        )],
    ))
    mock_provider.queue_response(ModelResponse(content="Specialist summary."))
    mock_provider.queue_response(ModelResponse(content="Root summary."))

    selected_contexts = []

    def select_deterministic_mock(context):
        selected_contexts.append(context)
        return mock_provider, ModelSelection(
            provider_name="mock",
            model_name="mock-default",
            reason="deterministic routing propagation test",
            context=context,
        )

    monkeypatch.setattr(model_router, "select_model_for_task", select_deterministic_mock)
    response = await async_client.post(
        "/v1/chat",
        json={
            "session_id": f"rt-{specialist_name}-{expected_reasoning_effort}-{expected_lock}",
            "message": "Run the delegated task.",
            **overrides,
        },
    )
    assert response.status_code == 200, response.text
    parent = response.json()
    assert parent["status"] == "completed"

    result = await test_db_session.execute(
        select(RunModel).where(RunModel.parent_run_id == parent["run_id"])
    )
    child = result.scalar_one()
    snapshot = child.routing_snapshot_json

    assert child.status == "completed"
    assert snapshot["is_lock_all"] is expected_lock
    assert snapshot["explicit_model_override"] == expected_model
    assert snapshot["reasoning_policy"] == expected_reasoning_policy
    assert snapshot["reasoning_effort"] == expected_reasoning_effort
    assert any(context.run_id == child.id for context in selected_contexts)


@pytest.mark.asyncio
async def test_root_then_child_routing_confirmations_resume_sequentially(
    async_client, test_db_session, monkeypatch
):
    """A root route decision can lead to a separate child decision in one run."""
    mock_provider = model_router.get_provider("mock")
    mock_provider.queue_response(ModelResponse(
        content="The root route is approved; delegate the review.",
        tool_calls=[ToolCallRequest(
            id="delegate-after-root-route-confirmation",
            name="delegate_task",
            arguments={
                "specialist_name": "coding",
                "task_description": "Review this change.",
            },
        )],
    ))
    mock_provider.queue_response(ModelResponse(content="Child review completed."))
    mock_provider.queue_response(ModelResponse(content="The review is complete."))

    root_run_id = None
    contexts = []

    def require_confirmation_per_run(context):
        nonlocal root_run_id
        contexts.append(context)
        if context and root_run_id is None:
            root_run_id = context.run_id
        if context and not context.explicit_model_override:
            raise RoutingConfirmationRequired(
                "Cloud fallback requires confirmation.",
                {"proposed_provider": "openai", "proposed_model": "gpt-4o-mini"},
            )
        if context and context.explicit_model_override:
            return mock_provider, ModelSelection(
                provider_name="mock",
                model_name="mock-default",
                reason=f"confirmed route {context.explicit_model_override}",
            )
        return mock_provider, ModelSelection(
            provider_name="mock",
            model_name="mock-default",
            reason="deterministic test route",
        )

    monkeypatch.setattr(model_router, "select_model_for_task", require_confirmation_per_run)
    started = await async_client.post(
        "/v1/chat",
        json={"session_id": "routing-confirm-root-then-child", "message": "Review this change."},
    )
    assert started.status_code == 200
    root_data = started.json()
    assert root_data["status"] == "waiting_for_routing_confirmation"
    assert mock_provider.call_history == []

    root_confirmation = await test_db_session.get(
        RoutingConfirmationModel, root_data["routing_confirmation_id"]
    )
    assert root_confirmation.execution_run_id == root_confirmation.root_run_id

    approved_root = await async_client.post(
        f"/v1/routing-confirmations/{root_confirmation.id}/decision",
        json={"decision": "approved"},
    )
    assert approved_root.status_code == 200
    root_decision = approved_root.json()
    assert root_decision["status"] == "approved"
    assert root_decision["execution_status"] == "waiting_for_routing_confirmation"
    child_confirmation_id = root_decision["next_routing_confirmation_id"]
    assert child_confirmation_id

    child_confirmation = await test_db_session.get(
        RoutingConfirmationModel, child_confirmation_id
    )
    assert child_confirmation.root_run_id == root_data["run_id"]
    assert child_confirmation.execution_run_id != child_confirmation.root_run_id
    child_run = await test_db_session.get(RunModel, child_confirmation.execution_run_id)
    assert child_run.status == "waiting_for_routing_confirmation"

    approved_child = await async_client.post(
        f"/v1/routing-confirmations/{child_confirmation.id}/decision",
        json={"decision": "approved"},
    )
    assert approved_child.status_code == 200
    assert approved_child.json()["status"] == "approved"
    assert approved_child.json()["execution_status"] == "completed"
    assert len(mock_provider.call_history) == 3
    assert sum(
        context is not None
        and context.run_id == root_data["run_id"]
        and context.explicit_model_override == "openai:gpt-4o-mini"
        for context in contexts
    ) >= 2

    root_run = await test_db_session.get(RunModel, root_data["run_id"])
    child_run = await test_db_session.get(RunModel, child_confirmation.execution_run_id)
    assert root_run.status == "completed"
    assert child_run.status == "completed"
    assert root_confirmation.status == "approved"
    assert child_confirmation.status == "approved"
