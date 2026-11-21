"""Startup reconciliation for root runs whose executor disappeared."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.run_recovery import _INTERRUPTED_RESPONSE, recover_running_root_runs
from app.api.run_resume_lock import lock_run_execution
from app.db.models import (
    ApprovalModel,
    DelegationModel,
    MessageModel,
    RoutingConfirmationModel,
    RunEventModel,
    RunModel,
    RunStatus,
    SessionModel,
    utc_now,
)


class SnapshotGraph:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    async def aget_state(self, config):
        run_id = config["configurable"]["thread_id"]
        return self.snapshots.get(run_id, SimpleNamespace(values={}, next=(), tasks=()))


async def _create_running_chat(db, *, run_id: str, session_id: str) -> RunModel:
    db.add(SessionModel(id=session_id, title="Recovery test", metadata_json={}))
    run = RunModel(
        id=run_id,
        session_id=session_id,
        client_turn_id=f"turn-{run_id}",
        request_fingerprint="fingerprint",
        status=RunStatus.RUNNING.value,
        user_message="Please recover this run.",
        routing_snapshot_json={"privacy_policy": "public"},
    )
    db.add(run)
    db.add(RunEventModel(run_id=run_id, event_type="run_executor_started", payload={"source": "chat"}))
    await db.commit()
    return run


async def _create_running_event_run(
    db,
    *,
    run_id: str,
    session_id: str,
    executor_started: bool,
) -> RunModel:
    db.add(SessionModel(id=session_id, title="Event recovery test", metadata_json={}))
    run = RunModel(
        id=run_id,
        session_id=session_id,
        status=RunStatus.RUNNING.value,
        user_message="Please recover this event run.",
        routing_snapshot_json={"privacy_policy": "local_only"},
    )
    db.add(run)
    if executor_started:
        db.add(RunEventModel(
            run_id=run_id,
            event_type="run_executor_started",
            payload={"source": "event"},
        ))
    await db.commit()
    return run


@pytest.mark.asyncio
async def test_reconciles_terminal_checkpoint_without_replaying_graph(test_db_session):
    run = await _create_running_chat(test_db_session, run_id="recover-terminal", session_id="recover-terminal-session")
    graph = SnapshotGraph({
        run.id: SimpleNamespace(
            values={
                "run_id": run.id,
                "execution_status": RunStatus.COMPLETED.value,
                "final_response": "Recovered answer.",
            },
            next=(),
            tasks=(),
        )
    })

    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(run)
    assert result["terminal"] == 1
    assert run.status == RunStatus.COMPLETED.value
    assert run.final_response == "Recovered answer."


@pytest.mark.asyncio
async def test_recovers_started_legacy_chat_without_client_turn_id(test_db_session):
    started = await _create_running_chat(
        test_db_session,
        run_id="recover-legacy-chat-started",
        session_id="recover-legacy-chat-started-session",
    )
    started.client_turn_id = None
    unstarted = RunModel(
        id="recover-legacy-chat-unstarted",
        session_id="recover-legacy-chat-unstarted-session",
        user_message="This chat executor never started.",
        status=RunStatus.RUNNING.value,
    )
    test_db_session.add(SessionModel(id=unstarted.session_id, title="Unstarted legacy chat", metadata_json={}))
    test_db_session.add(unstarted)
    await test_db_session.commit()

    graph = SnapshotGraph({
        started.id: SimpleNamespace(
            values={"execution_status": RunStatus.RUNNING.value},
            next=("execute_tool",),
            tasks=(),
        )
    })
    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(started)
    await test_db_session.refresh(unstarted)
    assert result["interrupted"] == 1
    assert started.status == RunStatus.FAILED.value
    assert unstarted.status == RunStatus.RUNNING.value


@pytest.mark.asyncio
async def test_restores_waiting_approval_from_matching_checkpoint(test_db_session):
    run = await _create_running_chat(test_db_session, run_id="recover-approval", session_id="recover-approval-session")
    approval = ApprovalModel(
        id="recover-approval-id",
        run_id=run.id,
        session_id=run.session_id,
        tool_name="write_file",
        tool_input={"path": "result.txt"},
        status="pending",
    )
    test_db_session.add(approval)
    await test_db_session.commit()
    graph = SnapshotGraph({
        run.id: SimpleNamespace(
            values={"run_id": run.id, "execution_status": RunStatus.RUNNING.value},
            next=("route_decision",),
            tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value={"approval_id": approval.id})])],
        )
    })

    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(run)
    assert result["waiting"] == 1
    assert run.status == RunStatus.WAITING_FOR_APPROVAL.value


@pytest.mark.asyncio
async def test_restores_waiting_child_approval_and_delegation(test_db_session):
    root = await _create_running_chat(
        test_db_session,
        run_id="recover-child-approval-root",
        session_id="recover-child-approval-session",
    )
    child = RunModel(
        id="recover-child-approval-run",
        session_id=root.session_id,
        user_message="[Specialist: research] Inspect this question.",
        parent_run_id=root.id,
        status=RunStatus.RUNNING.value,
    )
    delegation = DelegationModel(
        parent_run_id=root.id,
        parent_tool_call_id="delegate-call-1",
        child_run_id=child.id,
        specialist_name="research",
        status=RunStatus.RUNNING.value,
    )
    approval = ApprovalModel(
        id="recover-child-approval-id",
        run_id=child.id,
        session_id=root.session_id,
        tool_name="write_file",
        tool_input={"path": "result.txt"},
        status="pending",
    )
    test_db_session.add_all([child, delegation, approval])
    await test_db_session.commit()
    graph = SnapshotGraph({
        root.id: SimpleNamespace(values={"execution_status": RunStatus.RUNNING.value}, next=("execute_tool",), tasks=()),
        child.id: SimpleNamespace(
            values={"execution_status": RunStatus.RUNNING.value},
            next=("route_decision",),
            tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value={"approval_id": approval.id})])],
        ),
    })

    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(root)
    await test_db_session.refresh(child)
    await test_db_session.refresh(delegation)
    assert result["waiting"] == 1
    assert root.status == RunStatus.WAITING_FOR_APPROVAL.value
    assert child.status == RunStatus.WAITING_FOR_APPROVAL.value
    assert delegation.status == RunStatus.WAITING_FOR_APPROVAL.value
    assert delegation.pending_approval_id == approval.id


@pytest.mark.asyncio
async def test_restores_waiting_routing_confirmation(test_db_session):
    run = await _create_running_chat(
        test_db_session,
        run_id="recover-routing-confirmation",
        session_id="recover-routing-confirmation-session",
    )
    confirmation = RoutingConfirmationModel(
        id="recover-routing-confirmation-id",
        root_run_id=run.id,
        execution_run_id=run.id,
        session_id=run.session_id,
        proposed_provider="cloud-provider",
        proposed_model="model-name",
        status="pending",
    )
    test_db_session.add(confirmation)
    await test_db_session.commit()
    graph = SnapshotGraph({
        run.id: SimpleNamespace(
            values={"execution_status": RunStatus.RUNNING.value},
            next=("reason",),
            tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value={
                "kind": "routing_confirmation",
                "confirmation_id": confirmation.id,
            })])],
        )
    })

    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(run)
    assert result["waiting"] == 1
    assert run.status == RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value


@pytest.mark.asyncio
async def test_finalizes_persisted_cancellation_after_root_executor_is_lost(test_db_session):
    root = await _create_running_chat(
        test_db_session,
        run_id="recover-cancelled-root",
        session_id="recover-cancelled-session",
    )
    root.cancel_requested_at = utc_now()
    child = RunModel(
        id="recover-cancelled-child",
        session_id=root.session_id,
        user_message="[Specialist: research] Find supporting evidence.",
        parent_run_id=root.id,
        status=RunStatus.WAITING_FOR_APPROVAL.value,
    )
    delegation = DelegationModel(
        parent_run_id=root.id,
        parent_tool_call_id="recover-cancelled-call",
        child_run_id=child.id,
        specialist_name="research",
        status=RunStatus.WAITING_FOR_APPROVAL.value,
        pending_approval_id="recover-cancelled-approval",
    )
    approval = ApprovalModel(
        id="recover-cancelled-approval",
        run_id=child.id,
        session_id=root.session_id,
        tool_name="write_file",
        tool_input={"path": "result.txt"},
        status="pending",
    )
    confirmation = RoutingConfirmationModel(
        id="recover-cancelled-confirmation",
        root_run_id=root.id,
        execution_run_id=child.id,
        session_id=root.session_id,
        proposed_provider="cloud-provider",
        proposed_model="model-name",
        status="pending",
    )
    test_db_session.add_all([child, delegation, approval, confirmation])
    await test_db_session.commit()

    class NoCheckpointReadGraph:
        async def aget_state(self, _config):
            raise AssertionError("a cancelled run must not resume or inspect its graph")

    result = await recover_running_root_runs(test_db_session, graph=NoCheckpointReadGraph())

    await test_db_session.refresh(root)
    await test_db_session.refresh(child)
    await test_db_session.refresh(delegation)
    await test_db_session.refresh(approval)
    await test_db_session.refresh(confirmation)
    assert result["cancelled"] == 1
    assert root.status == RunStatus.CANCELLED.value
    assert root.final_response.startswith("Run cancelled.")
    assert root.error_message is None
    assert child.status == RunStatus.CANCELLED.value
    assert delegation.status == RunStatus.CANCELLED.value
    assert delegation.pending_approval_id is None
    assert approval.status == "rejected"
    assert confirmation.status == "rejected"
    messages = list((await test_db_session.scalars(
        select(MessageModel).where(MessageModel.session_id == root.session_id)
    )).all())
    assert {message.role for message in messages} == {"user", "assistant"}
    assert next(message.content for message in messages if message.role == "assistant") == root.final_response
    recovery_event = await test_db_session.scalar(
        select(RunEventModel).where(
            RunEventModel.run_id == root.id,
            RunEventModel.event_type == "run_recovered",
        )
    )
    assert recovery_event.payload == {"recovery_action": "cancelled", "source": "cancel_request"}


@pytest.mark.asyncio
async def test_fails_ambiguous_checkpoint_without_reexecuting_it(test_db_session):
    run = await _create_running_chat(test_db_session, run_id="recover-ambiguous", session_id="recover-ambiguous-session")
    graph = SnapshotGraph({
        run.id: SimpleNamespace(
            values={"run_id": run.id, "execution_status": RunStatus.RUNNING.value},
            next=("execute_tool",),
            tasks=(),
        )
    })

    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(run)
    assert result["interrupted"] == 1
    assert run.status == RunStatus.FAILED.value
    assert run.final_response == _INTERRUPTED_RESPONSE
    messages = list((await test_db_session.scalars(
        select(MessageModel).where(MessageModel.session_id == run.session_id).order_by(MessageModel.created_at)
    )).all())
    assert len(messages) == 2
    assert {message.role for message in messages} == {"user", "assistant"}
    assert next(message.content for message in messages if message.role == "assistant") == _INTERRUPTED_RESPONSE


@pytest.mark.asyncio
async def test_recovers_started_event_run_but_leaves_unstarted_event_for_outbox_retry(test_db_session):
    started = await _create_running_event_run(
        test_db_session,
        run_id="recover-event-started",
        session_id="recover-event-started-session",
        executor_started=True,
    )
    unstarted = await _create_running_event_run(
        test_db_session,
        run_id="recover-event-unstarted",
        session_id="recover-event-unstarted-session",
        executor_started=False,
    )
    graph = SnapshotGraph({
        started.id: SimpleNamespace(
            values={"run_id": started.id, "execution_status": RunStatus.RUNNING.value},
            next=("execute_tool",),
            tasks=(),
        )
    })

    result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(started)
    await test_db_session.refresh(unstarted)
    assert result["interrupted"] == 1
    assert started.status == RunStatus.FAILED.value
    assert started.final_response == _INTERRUPTED_RESPONSE
    assert unstarted.status == RunStatus.RUNNING.value
    messages = list((await test_db_session.scalars(
        select(MessageModel).where(MessageModel.session_id == started.session_id)
    )).all())
    assert {message.role for message in messages} == {"user", "assistant"}
    assert next(message.content for message in messages if message.role == "assistant") == _INTERRUPTED_RESPONSE


@pytest.mark.asyncio
async def test_skips_run_while_executor_lock_is_held(test_db_session):
    run = await _create_running_chat(test_db_session, run_id="recover-active", session_id="recover-active-session")
    graph = SnapshotGraph({})

    async with lock_run_execution(test_db_session, run.id):
        result = await recover_running_root_runs(test_db_session, graph=graph)

    await test_db_session.refresh(run)
    assert result["busy"] == 1
    assert run.status == RunStatus.RUNNING.value
