"""End-to-end cooperative cancellation across independent API requests."""

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.server import app
from app.db.base import Base
from app.db.models import ApprovalModel, MessageModel, RoutingConfirmationModel, RunEventModel, RunModel
from app.db.session import get_db
from app.models.base import ModelResponse


@pytest.mark.asyncio
async def test_live_chat_cancel_request_is_observed_after_inflight_model_call(async_client, tmp_path, monkeypatch):
    database_path = tmp_path / "run-cancellation.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def independent_db_sessions():
        async with factory() as session:
            yield session

    previous_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = independent_db_sessions
    model_call_started = asyncio.Event()
    release_model_call = asyncio.Event()

    async def slow_model_call(_request, provider_name=None):
        model_call_started.set()
        await release_model_call.wait()
        return ModelResponse(content="This response must be discarded after cancellation.")

    monkeypatch.setattr("app.models.router.model_router.route", slow_model_call)
    session_id = "cooperative-cancel-session"
    client_turn_id = "cooperative-cancel-turn"

    try:
        chat_task = asyncio.create_task(async_client.post("/v1/chat", json={
            "session_id": session_id,
            "client_turn_id": client_turn_id,
            "message": "Wait for cancellation while the model is working.",
        }))
        await asyncio.wait_for(model_call_started.wait(), timeout=5)
        active_state = await async_client.get(f"/v1/sessions/{session_id}/state")
        assert active_state.json()["run_status"] == "running"
        assert active_state.json()["client_turn_id"] == client_turn_id

        async with factory() as session:
            run = await session.scalar(select(RunModel).where(
                RunModel.session_id == session_id,
                RunModel.client_turn_id == client_turn_id,
            ))
            session.add_all([
                ApprovalModel(
                    id="cancel-race-approval",
                    run_id=run.id,
                    session_id=session_id,
                    tool_call_id="cancel-race-call",
                    tool_name="workspace.write",
                    tool_input={},
                    status="pending",
                ),
                RoutingConfirmationModel(
                    id="cancel-race-confirmation",
                    root_run_id=run.id,
                    execution_run_id=run.id,
                    session_id=session_id,
                    proposed_provider="cloud",
                    proposed_model="model",
                    status="pending",
                ),
            ])
            await session.commit()

        cancel_response = await async_client.post("/v1/runs/cancel-turn", json={
            "session_id": session_id,
            "client_turn_id": client_turn_id,
        })
        assert cancel_response.status_code == 202, cancel_response.text
        stopping_state = await async_client.get(f"/v1/sessions/{session_id}/state")
        assert stopping_state.json()["run_status"] == "cancellation_requested"
        assert stopping_state.json()["client_turn_id"] == client_turn_id
        release_model_call.set()

        chat_response = await asyncio.wait_for(chat_task, timeout=5)
        assert chat_response.status_code == 200, chat_response.text
        assert chat_response.json()["status"] == "cancelled"
        assert "must be discarded" not in chat_response.text
        finished_state = await async_client.get(f"/v1/sessions/{session_id}/state")
        assert finished_state.json()["run_status"] == "cancelled"
        assert finished_state.json()["client_turn_id"] is None

        async with factory() as session:
            run = await session.get(RunModel, cancel_response.json()["run_id"])
            events = list((await session.scalars(
                select(RunEventModel).where(RunEventModel.run_id == run.id)
            )).all())
            assert run.status == "cancelled"
            assert run.cancel_requested_at is not None
            assert "must be discarded" not in (run.final_response or "")
            assert {event.event_type for event in events} >= {"run_cancellation_requested", "run_cancelled"}
            approval = await session.get(ApprovalModel, "cancel-race-approval")
            confirmation = await session.get(RoutingConfirmationModel, "cancel-race-confirmation")
            messages = list((await session.scalars(
                select(MessageModel).where(MessageModel.session_id == session_id)
            )).all())
            assert approval.status == "rejected"
            assert confirmation.status == "rejected"
            assert all("must be discarded" not in message.content for message in messages)
    finally:
        release_model_call.set()
        app.dependency_overrides[get_db] = previous_override
        await engine.dispose()


@pytest.mark.asyncio
async def test_chat_stop_racing_terminalization_is_linearized(async_client, tmp_path, monkeypatch):
    database_path = tmp_path / "chat-cancellation-finalize-race.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def independent_db_sessions():
        async with factory() as session:
            yield session

    previous_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = independent_db_sessions
    model_call_started = asyncio.Event()
    release_model_call = asyncio.Event()
    status_read = asyncio.Event()
    release_finalization = asyncio.Event()
    original_refresh = AsyncSession.refresh
    session_id = str(uuid.uuid4())
    client_turn_id = "chat-finalization-race"

    async def slow_model_call(_request, provider_name=None):
        model_call_started.set()
        await release_model_call.wait()
        return ModelResponse(content="The answer is ready.")

    async def pause_after_status_read(session, instance, *args, **kwargs):
        result = await original_refresh(session, instance, *args, **kwargs)
        if isinstance(instance, RunModel) and instance.client_turn_id == client_turn_id:
            status_read.set()
            await release_finalization.wait()
        return result

    monkeypatch.setattr("app.models.router.model_router.route", slow_model_call)
    monkeypatch.setattr(AsyncSession, "refresh", pause_after_status_read)

    try:
        chat_task = asyncio.create_task(async_client.post("/v1/chat", json={
            "session_id": session_id,
            "client_turn_id": client_turn_id,
            "message": "race at finalization",
        }))
        await asyncio.wait_for(model_call_started.wait(), timeout=5)
        release_model_call.set()
        await asyncio.wait_for(status_read.wait(), timeout=5)

        cancel = await async_client.post("/v1/runs/cancel-turn", json={
            "session_id": session_id,
            "client_turn_id": client_turn_id,
        })
        release_finalization.set()
        chat = await asyncio.wait_for(chat_task, timeout=5)

        assert cancel.status_code == 202, cancel.text
        assert cancel.json()["status"] == "cancellation_requested"
        assert chat.status_code == 200, chat.text
        assert chat.json()["status"] == "cancelled"
        assert chat.json()["response"].startswith("Run cancelled.")

        async with factory() as session:
            run = await session.get(RunModel, cancel.json()["run_id"])
            assert run.status == "cancelled"
            assert run.cancel_requested_at is not None
            assert run.final_response.startswith("Run cancelled.")
            events = list((await session.scalars(
                select(RunEventModel).where(RunEventModel.run_id == run.id)
            )).all())
            assert {event.event_type for event in events} >= {
                "run_cancellation_requested",
                "run_cancelled",
            }
    finally:
        release_model_call.set()
        release_finalization.set()
        app.dependency_overrides[get_db] = previous_override
        await engine.dispose()
