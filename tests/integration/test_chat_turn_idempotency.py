"""Client retries of one chat turn must return its durable run, not invoke it again."""

import pytest
from sqlalchemy import func, select

from app.db.models import MessageModel, RunModel
from app.models.router import model_router


@pytest.mark.asyncio
async def test_duplicate_chat_turn_returns_original_run_without_second_model_call(
    async_client,
    test_db_session,
):
    body = {
        "session_id": "chat-idempotency-session",
        "client_turn_id": "turn-stable-001",
        "message": "Explain why this retry must not create another run.",
    }

    first = await async_client.post("/v1/chat", json=body)
    assert first.status_code == 200
    first_data = first.json()
    provider = model_router.get_provider("mock")
    call_count = len(provider.call_history)
    assert call_count > 0

    replay = await async_client.post("/v1/chat", json=body)
    assert replay.status_code == 200
    replay_data = replay.json()

    assert replay_data["run_id"] == first_data["run_id"]
    assert replay_data["status"] == first_data["status"]
    assert replay_data["response"] == first_data["response"]
    assert replay_data["user_message_id"] == first_data["user_message_id"]
    assert replay_data["assistant_message_id"] == first_data["assistant_message_id"]
    assert len(provider.call_history) == call_count
    assert await test_db_session.scalar(
        select(func.count()).select_from(RunModel).where(RunModel.session_id == body["session_id"])
    ) == 1
    assert await test_db_session.scalar(
        select(func.count()).select_from(MessageModel).where(MessageModel.session_id == body["session_id"])
    ) == 2


@pytest.mark.asyncio
async def test_chat_turn_id_cannot_be_reused_for_a_different_request(async_client):
    body = {
        "session_id": "chat-idempotency-conflict-session",
        "client_turn_id": "turn-stable-002",
        "message": "Original request.",
    }
    first = await async_client.post("/v1/chat", json=body)
    assert first.status_code == 200
    call_count = len(model_router.get_provider("mock").call_history)

    conflicting = await async_client.post(
        "/v1/chat",
        json={**body, "message": "A different request with the same key."},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"]["code"] == "ChatTurnIdConflict"
    assert len(model_router.get_provider("mock").call_history) == call_count
