"""Durable ask-before-cloud confirmation lifecycle tests."""

import pytest

from app.core.errors import RoutingConfirmationRequired
from app.db.models import RunModel, RoutingConfirmationModel
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
