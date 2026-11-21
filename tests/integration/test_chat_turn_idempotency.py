"""Client retries must return durable chat runs without invoking them again."""

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.db.models import MessageModel, RunEventModel, RunModel, RunStatus, utc_now
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


@pytest.mark.asyncio
@pytest.mark.parametrize("client_turn_id", ["chat-recovery-race-turn", None])
async def test_chat_does_not_start_after_recovery_finishes_run_before_executor_lock(
    async_client,
    test_db_session,
    monkeypatch,
    client_turn_id,
):
    from app.api.run_recovery import _INTERRUPTED_RESPONSE, recover_running_root_runs

    session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chat-recovery-before-lock-{client_turn_id or 'legacy'}"))

    class RecoveryGraph:
        async def aget_state(self, _config):
            return SimpleNamespace(values={}, next=(), tasks=())

        async def ainvoke(self, *_args, **_kwargs):
            raise AssertionError("a recovered terminal chat run must not invoke the graph")

    graph = RecoveryGraph()

    async def recover_run_before_handler_acquires_execution_lock():
        run = await test_db_session.scalar(select(RunModel).where(RunModel.session_id == session_id))
        assert run is not None
        run.created_at = utc_now() - timedelta(minutes=3)
        await test_db_session.commit()
        result = await recover_running_root_runs(test_db_session, graph=graph)
        assert result["interrupted"] == 1
        return graph

    monkeypatch.setattr(
        "app.api.routes.chat.get_compiled_graph",
        recover_run_before_handler_acquires_execution_lock,
    )
    body = {"session_id": session_id, "message": "Do not execute after recovery."}
    if client_turn_id is not None:
        body["client_turn_id"] = client_turn_id

    response = await async_client.post("/v1/chat", json=body)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == RunStatus.FAILED.value
    assert data["response"] == _INTERRUPTED_RESPONSE
    run = await test_db_session.scalar(select(RunModel).where(RunModel.session_id == session_id))
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert await test_db_session.scalar(
        select(func.count()).select_from(RunEventModel).where(
            RunEventModel.run_id == run.id,
            RunEventModel.event_type == "run_executor_started",
        )
    ) == 0
