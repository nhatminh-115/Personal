"""Conservative startup reconciliation for interrupted root chat turns."""

from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.run_resume_lock import try_lock_run_execution, try_lock_run_resume
from app.core.logging import logger
from app.db.models import (
    ApprovalModel,
    DelegationModel,
    MessageModel,
    RoutingConfirmationModel,
    RunEventModel,
    RunModel,
    RunStatus,
    WorkspaceObjectModel,
    utc_now,
)
from app.memory.service import SQLMemoryService
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph


_ACTIVE_STATUSES = {
    RunStatus.CREATED.value,
    RunStatus.RUNNING.value,
    RunStatus.WAITING_FOR_APPROVAL.value,
    RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value,
}
_TERMINAL_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
}
_VALID_APPROVAL_STATUSES = {"pending", "approved", "edited", "rejected"}
_VALID_CONFIRMATION_STATUSES = {"pending", "approved", "rejected"}
_INTERRUPTED_RESPONSE = (
    "Run interrupted because its executor stopped before AURA reached a safe recovery point. "
    "Review the run history before retrying."
)
_INTERRUPTED_ERROR = "The chat executor stopped before the run could be safely recovered."
_LEGACY_RECOVERY_GRACE = timedelta(minutes=2)
RECOVERY_SCAN_INTERVAL_SECONDS = 60


def _snapshot_interrupts(snapshot: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for task in getattr(snapshot, "tasks", ()):
        for interrupt_item in getattr(task, "interrupts", ()):
            value = getattr(interrupt_item, "value", interrupt_item)
            if isinstance(value, dict):
                result.append(value)
    return result


async def _has_executor_started(db: AsyncSession, run_id: str) -> bool:
    event_id = await db.scalar(
        select(RunEventModel.id)
        .where(
            RunEventModel.run_id == run_id,
            RunEventModel.event_type == "run_executor_started",
        )
        .limit(1)
    )
    return event_id is not None


async def _terminal_state_is_safe(
    db: AsyncSession,
    run: RunModel,
    snapshot: Any,
) -> tuple[bool, Optional[str], Optional[str]]:
    values = getattr(snapshot, "values", None)
    if not isinstance(values, dict):
        return False, None, None

    state_status = values.get("execution_status")
    if state_status not in _TERMINAL_STATUSES:
        return False, None, None

    if not getattr(snapshot, "next", ()):
        return True, state_status, values.get("final_response")

    terminal_event = {
        RunStatus.COMPLETED.value: "run_completed",
        RunStatus.FAILED.value: "run_failed",
        RunStatus.CANCELLED.value: "run_cancelled",
    }[state_status]
    event_id = await db.scalar(
        select(RunEventModel.id)
        .where(
            RunEventModel.run_id == run.id,
            RunEventModel.event_type == terminal_event,
        )
        .limit(1)
    )
    if event_id is not None:
        return True, state_status, values.get("final_response")

    # A completed/cancelled reply is persisted before the final trace event. If
    # a crash lands in that narrow window, retain the answer without replaying
    # memory writes or tools from the node.
    if state_status in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value}:
        assistant_id = await db.scalar(
            select(MessageModel.id)
            .where(
                MessageModel.session_id == run.session_id,
                MessageModel.role == "assistant",
                MessageModel.metadata_json["run_id"].as_string() == run.id,
            )
            .limit(1)
        )
        if assistant_id is not None:
            return True, state_status, values.get("final_response")

    return False, None, None


async def _resolve_checkpoint_interrupt(
    db: AsyncSession,
    root: RunModel,
    run_ids: set[str],
    snapshots: dict[str, Any],
) -> tuple[Optional[str], dict[str, str], Optional[str]]:
    """Match saved LangGraph interrupts to their durable decision records."""
    for snapshot in snapshots.values():
        for interrupt_value in _snapshot_interrupts(snapshot):
            if interrupt_value.get("kind") == "routing_confirmation":
                confirmation_id = interrupt_value.get("confirmation_id")
                if not isinstance(confirmation_id, str):
                    continue
                confirmation = await db.get(RoutingConfirmationModel, confirmation_id)
                if (
                    confirmation is None
                    or confirmation.root_run_id != root.id
                    or confirmation.execution_run_id not in run_ids
                    or confirmation.status not in _VALID_CONFIRMATION_STATUSES
                ):
                    continue
                return (
                    RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value,
                    {confirmation.execution_run_id: RunStatus.WAITING_FOR_ROUTING_CONFIRMATION.value},
                    confirmation_id,
                )

            approval_id = interrupt_value.get("approval_id")
            if not isinstance(approval_id, str):
                continue
            approval = await db.get(ApprovalModel, approval_id)
            if (
                approval is None
                or approval.run_id not in run_ids
                or approval.status not in _VALID_APPROVAL_STATUSES
            ):
                continue
            return (
                RunStatus.WAITING_FOR_APPROVAL.value,
                {approval.run_id: RunStatus.WAITING_FOR_APPROVAL.value},
                approval_id,
            )

    return None, {}, None


async def _persist_interrupted_chat_messages(db: AsyncSession, run: RunModel) -> None:
    result = await db.execute(
        select(MessageModel)
        .where(
            MessageModel.session_id == run.session_id,
            MessageModel.metadata_json["run_id"].as_string() == run.id,
            MessageModel.role.in_(["user", "assistant"]),
        )
        .order_by(MessageModel.created_at, MessageModel.id)
    )
    messages = list(result.scalars())
    roles = {message.role for message in messages}
    privacy_policy = (run.routing_snapshot_json or {}).get("privacy_policy", "public")
    memory = SQLMemoryService(db)

    if "user" not in roles:
        await memory.save_message(
            run.session_id,
            role="user",
            content=run.user_message,
            metadata={"run_id": run.id, "privacy_policy": privacy_policy},
        )

    assistant_messages = [message for message in messages if message.role == "assistant"]
    if assistant_messages:
        message_ids = [message.id for message in assistant_messages]
        for message in assistant_messages:
            message.content = _INTERRUPTED_RESPONSE
        await db.execute(
            update(WorkspaceObjectModel)
            .where(WorkspaceObjectModel.source_message_id.in_(message_ids))
            .values(content=_INTERRUPTED_RESPONSE, title=_INTERRUPTED_RESPONSE[:255])
        )
        await db.commit()
    else:
        await memory.save_message(
            run.session_id,
            role="assistant",
            content=_INTERRUPTED_RESPONSE,
            metadata={"run_id": run.id, "privacy_policy": privacy_policy},
        )


async def _mark_interrupted(
    db: AsyncSession,
    root: RunModel,
    runs: list[RunModel],
    trace_service: TraceService,
) -> None:
    interrupted_runs = [run for run in runs if run.status in _ACTIVE_STATUSES]
    for run in interrupted_runs:
        run.status = RunStatus.FAILED.value
        run.error_message = _INTERRUPTED_ERROR
        run.final_response = _INTERRUPTED_RESPONSE

    all_run_ids = [run.id for run in runs]
    await db.execute(
        update(ApprovalModel)
        .where(ApprovalModel.run_id.in_(all_run_ids), ApprovalModel.status == "pending")
        .values(
            status="rejected",
            decision_notes="Executor stopped before the run could be safely recovered.",
            decided_at=utc_now(),
        )
    )
    await db.execute(
        update(RoutingConfirmationModel)
        .where(
            RoutingConfirmationModel.root_run_id == root.id,
            RoutingConfirmationModel.status == "pending",
        )
        .values(
            status="rejected",
            decision_notes="Executor stopped before the run could be safely recovered.",
            decided_at=utc_now(),
        )
    )

    child_ids = [run.id for run in interrupted_runs if run.parent_run_id == root.id]
    if child_ids:
        await db.execute(
            update(DelegationModel)
            .where(DelegationModel.child_run_id.in_(child_ids))
            .values(
                status=RunStatus.FAILED.value,
                result_summary=_INTERRUPTED_RESPONSE,
                pending_approval_id=None,
            )
        )

    await _persist_interrupted_chat_messages(db, root)
    for run in interrupted_runs:
        await trace_service.record_event(
            run_id=run.id,
            session_id=run.session_id,
            event_type="run_interrupted",
            payload={"recovery_action": "failed_safe", "error_category": "executor_lost"},
        )


async def _sync_terminal_run(
    db: AsyncSession,
    run: RunModel,
    state_status: str,
    final_response: Optional[str],
) -> None:
    run.status = state_status
    run.final_response = final_response
    if state_status != RunStatus.FAILED.value:
        run.error_message = None
    delegation = await db.scalar(
        select(DelegationModel).where(DelegationModel.child_run_id == run.id)
    )
    if delegation is not None:
        delegation.status = state_status
        delegation.result_summary = final_response
        delegation.pending_approval_id = None


async def _fail_orphan_children(
    db: AsyncSession,
    root: RunModel,
    runs: list[RunModel],
    trace_service: TraceService,
) -> None:
    children = [run for run in runs[1:] if run.status in _ACTIVE_STATUSES]
    if not children:
        return

    child_ids = [run.id for run in children]
    for child in children:
        child.status = RunStatus.FAILED.value
        child.final_response = _INTERRUPTED_RESPONSE
        child.error_message = _INTERRUPTED_ERROR

    await db.execute(
        update(ApprovalModel)
        .where(ApprovalModel.run_id.in_(child_ids), ApprovalModel.status == "pending")
        .values(
            status="rejected",
            decision_notes="Executor stopped before the run could be safely recovered.",
            decided_at=utc_now(),
        )
    )
    await db.execute(
        update(RoutingConfirmationModel)
        .where(
            RoutingConfirmationModel.root_run_id == root.id,
            RoutingConfirmationModel.execution_run_id.in_(child_ids),
            RoutingConfirmationModel.status == "pending",
        )
        .values(
            status="rejected",
            decision_notes="Executor stopped before the run could be safely recovered.",
            decided_at=utc_now(),
        )
    )
    await db.execute(
        update(DelegationModel)
        .where(DelegationModel.child_run_id.in_(child_ids))
        .values(
            status=RunStatus.FAILED.value,
            result_summary=_INTERRUPTED_RESPONSE,
            pending_approval_id=None,
        )
    )
    for child in children:
        await trace_service.record_event(
            run_id=child.id,
            session_id=child.session_id,
            event_type="run_interrupted",
            payload={"recovery_action": "failed_safe", "error_category": "orphaned_child"},
        )


async def _recover_one_root(db: AsyncSession, graph: Any, root: RunModel) -> str:
    child_rows = list((await db.scalars(
        select(RunModel).where(
            RunModel.parent_run_id == root.id,
            RunModel.status.in_(_ACTIVE_STATUSES),
        )
    )).all())
    runs = [root, *child_rows]
    snapshots: dict[str, Any] = {}
    trace_service = TraceService(db)

    async with AsyncExitStack() as lock_stack:
        for run_id in sorted({run.id for run in runs}):
            acquired = await lock_stack.enter_async_context(try_lock_run_resume(db, run_id))
            if not acquired:
                return "busy"

        acquired = await lock_stack.enter_async_context(try_lock_run_execution(db, root.id))
        if not acquired:
            return "busy"

        for run in runs:
            await db.refresh(run)
        if root.status != RunStatus.RUNNING.value or root.cancel_requested_at is not None:
            return "changed"

        for run in runs:
            snapshots[run.id] = await graph.aget_state({"configurable": {"thread_id": run.id}})

        run_ids = {run.id for run in runs}
        wait_status, waiting_runs, decision_id = await _resolve_checkpoint_interrupt(
            db, root, run_ids, snapshots
        )
        if wait_status is not None:
            for run_id, run_status in waiting_runs.items():
                run_by_id = next(item for item in runs if item.id == run_id)
                run_by_id.status = run_status
                if run_by_id.parent_run_id:
                    delegation = await db.scalar(
                        select(DelegationModel).where(DelegationModel.child_run_id == run_id)
                    )
                    if delegation is not None:
                        delegation.status = run_status
                        delegation.pending_approval_id = (
                            decision_id
                            if run_status == RunStatus.WAITING_FOR_APPROVAL.value
                            else None
                        )
            root.status = wait_status
            await db.commit()
            await trace_service.record_event(
                run_id=root.id,
                session_id=root.session_id,
                event_type="run_recovered",
                payload={"recovery_action": wait_status, "decision_id": decision_id},
            )
            return "waiting"

        for run in runs[1:]:
            terminal, state_status, final_response = await _terminal_state_is_safe(
                db, run, snapshots[run.id]
            )
            if terminal and state_status is not None:
                await _sync_terminal_run(db, run, state_status, final_response)

        terminal, state_status, final_response = await _terminal_state_is_safe(
            db, root, snapshots[root.id]
        )
        if terminal and state_status is not None:
            await _sync_terminal_run(db, root, state_status, final_response)
            await _fail_orphan_children(db, root, runs, trace_service)
            await db.commit()
            await trace_service.record_event(
                run_id=root.id,
                session_id=root.session_id,
                event_type="run_recovered",
                payload={"recovery_action": state_status, "source": "terminal_checkpoint"},
            )
            return "terminal"

        await _mark_interrupted(db, root, runs, trace_service)
        await db.commit()
        return "interrupted"


async def recover_running_chat_runs(
    db: Optional[AsyncSession] = None,
    *,
    graph: Any = None,
) -> dict[str, int]:
    """Reconcile idle root chat runs without replaying an ambiguous checkpoint."""
    if db is None:
        from app.db import session as db_session

        async with db_session.async_session_factory() as startup_session:
            return await recover_running_chat_runs(startup_session, graph=graph)

    root_ids = list((await db.scalars(
        select(RunModel.id)
        .where(
            RunModel.parent_run_id.is_(None),
            RunModel.client_turn_id.is_not(None),
            RunModel.status == RunStatus.RUNNING.value,
            RunModel.cancel_requested_at.is_(None),
        )
        .order_by(RunModel.created_at, RunModel.id)
    )).all())
    if not root_ids:
        return {"waiting": 0, "terminal": 0, "interrupted": 0, "busy": 0, "skipped": 0}

    if graph is None:
        graph = await get_compiled_graph()

    counts = {"waiting": 0, "terminal": 0, "interrupted": 0, "busy": 0, "skipped": 0}
    legacy_cutoff = utc_now() - _LEGACY_RECOVERY_GRACE
    for root_id in root_ids:
        root = await db.get(RunModel, root_id)
        if root is None or root.status != RunStatus.RUNNING.value:
            continue
        if not await _has_executor_started(db, root.id):
            created_at = root.created_at
            if created_at.tzinfo is None:
                from datetime import timezone

                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at >= legacy_cutoff:
                counts["skipped"] += 1
                continue
        try:
            outcome = await _recover_one_root(db, graph, root)
            counts[outcome] = counts.get(outcome, 0) + 1
        except Exception as exc:
            await db.rollback()
            logger.error(
                "Could not reconcile interrupted chat run '%s' (error type: %s).",
                root_id,
                type(exc).__name__,
            )
            counts["skipped"] += 1

    return counts


async def run_chat_recovery_loop() -> None:
    """Periodically recover executors lost while this API process is running."""
    import asyncio

    while True:
        await asyncio.sleep(RECOVERY_SCAN_INTERVAL_SECONDS)
        try:
            counts = await recover_running_chat_runs()
            if any(counts.get(key, 0) for key in ("waiting", "terminal", "interrupted")):
                logger.info("Periodic chat-run recovery completed.", extra=counts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Periodic chat-run recovery failed (error type: %s); it will retry on the next scan.",
                type(exc).__name__,
            )
