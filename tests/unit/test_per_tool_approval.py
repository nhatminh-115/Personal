"""Unit tests for per-tool approval security and adversarial multi-tool scenarios."""

import os
from pathlib import Path
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.approvals.policy import PermissionPolicy
from app.approvals.service import ApprovalService
from app.core.settings import settings
from app.db.models import RunStatus
from app.models.base import ModelResponse, ToolCallRequest
from app.models.mock_provider import MockModelProvider
from app.models.router import ModelRouter
from app.observability.tracer import TraceService
from app.orchestrator.graph import get_compiled_graph
from app.tools.registry import ToolRegistry
from app.tools.workspace import ReadWorkspaceFileTool, WriteWorkspaceFileTool


@pytest.fixture
def clean_workspace(tmp_path):
    orig = settings.AURA_WORKSPACE_ROOT
    settings.AURA_WORKSPACE_ROOT = tmp_path
    yield tmp_path
    settings.AURA_WORKSPACE_ROOT = orig


@pytest.fixture
def custom_registry(clean_workspace):
    registry = ToolRegistry()
    registry.register(ReadWorkspaceFileTool())
    registry.register(WriteWorkspaceFileTool())
    return registry


@pytest.mark.asyncio
async def test_multi_tool_two_writes_require_two_approvals(test_db_session, clean_workspace, custom_registry):
    """
    Scenario 1: Two write calls in a single run.
    Must require two independent approvals.
    Approving the first must NOT execute the second prematurely.
    Both only execute when both are approved.
    """
    app_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)
    mock_provider = MockModelProvider()
    router = ModelRouter(providers={"mock": mock_provider}, default_provider="mock")

    # Queue model response requesting two distinct file writes
    tc1 = ToolCallRequest(id="call_write_1", name="write_workspace_file", arguments={"path": "file1.txt", "content": "Content 1"})
    tc2 = ToolCallRequest(id="call_write_2", name="write_workspace_file", arguments={"path": "file2.txt", "content": "Content 2"})
    mock_provider.queue_response(ModelResponse(content=None, tool_calls=[tc1, tc2], finish_reason="tool_calls"))
    mock_provider.queue_response(ModelResponse(content="Both files written successfully.", finish_reason="stop"))

    checkpointer = MemorySaver()
    graph = await get_compiled_graph(checkpointer=checkpointer)

    run_id = "run-multi-write-1"
    session_id = "session-multi-write"
    config = {
        "configurable": {
            "thread_id": run_id,
            "memory_service": None,
            "approval_service": app_service,
            "trace_service": trace_service,
            "tool_registry": custom_registry,
            "model_router": router,
        }
    }

    initial_state = {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": "Write file1.txt and file2.txt",
        "messages": [{"role": "user", "content": "Write file1.txt and file2.txt"}],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "tool_approvals": {},
        "execution_status": RunStatus.RUNNING.value,
        "errors": [],
        "final_response": None,
    }

    # Turn 1: Run graph until first interrupt
    await graph.ainvoke(initial_state, config=config)

    # Inspect snapshot: should be paused waiting on call_write_1
    snapshot1 = await graph.aget_state(config)
    assert bool(snapshot1.next) is True
    pending = await app_service.get_pending_approvals()
    assert len(pending) == 1
    app1 = pending[0]
    assert app1.tool_call_id == "call_write_1"
    assert app1.tool_name == "write_workspace_file"

    # Crucial security check: neither file1 nor file2 exists yet!
    assert not (clean_workspace / "file1.txt").exists()
    assert not (clean_workspace / "file2.txt").exists()

    # Resume with approval for call_write_1
    await app_service.record_decision(app1.id, "approved")
    await graph.ainvoke(Command(resume={"decision": "approved"}), config=config)

    # Graph should have looped back and paused on the SECOND tool call (call_write_2)
    snapshot2 = await graph.aget_state(config)
    assert bool(snapshot2.next) is True

    pending2 = await app_service.get_pending_approvals()
    assert len(pending2) == 1
    app2 = pending2[0]
    assert app2.tool_call_id == "call_write_2"
    assert app2.id != app1.id

    # Crucial check: file2 MUST NOT EXIST! Approval of call 1 did NOT authorize call 2!
    assert not (clean_workspace / "file2.txt").exists()

    # Now approve the second call
    await app_service.record_decision(app2.id, "approved")
    final_state = await graph.ainvoke(Command(resume={"decision": "approved"}), config=config)

    # Graph completed
    snapshot3 = await graph.aget_state(config)
    assert not snapshot3.next
    assert final_state["execution_status"] == RunStatus.COMPLETED.value

    # Both files now exist with exact content
    assert (clean_workspace / "file1.txt").exists()
    assert (clean_workspace / "file1.txt").read_text(encoding="utf-8") == "Content 1"
    assert (clean_workspace / "file2.txt").exists()
    assert (clean_workspace / "file2.txt").read_text(encoding="utf-8") == "Content 2"


@pytest.mark.asyncio
async def test_multi_tool_read_and_write(test_db_session, clean_workspace, custom_registry):
    """
    Scenario 2: Read (auto-permitted) + Write (requires approval).
    Read executes; write requires approval and does not execute until authorized.
    """
    app_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)
    mock_provider = MockModelProvider()
    router = ModelRouter(providers={"mock": mock_provider}, default_provider="mock")

    # Setup source file for read
    (clean_workspace / "source.txt").write_text("Source Data", encoding="utf-8")

    tc_read = ToolCallRequest(id="call_read_1", name="read_workspace_file", arguments={"path": "source.txt"})
    tc_write = ToolCallRequest(id="call_write_1", name="write_workspace_file", arguments={"path": "dest.txt", "content": "Dest Data"})
    mock_provider.queue_response(ModelResponse(content=None, tool_calls=[tc_read, tc_write], finish_reason="tool_calls"))
    mock_provider.queue_response(ModelResponse(content="Copy done.", finish_reason="stop"))

    checkpointer = MemorySaver()
    graph = await get_compiled_graph(checkpointer=checkpointer)

    run_id = "run-read-write-1"
    config = {
        "configurable": {
            "thread_id": run_id,
            "memory_service": None,
            "approval_service": app_service,
            "trace_service": trace_service,
            "tool_registry": custom_registry,
            "model_router": router,
        }
    }

    initial_state = {
        "run_id": run_id,
        "session_id": "session-rw",
        "user_message": "Read source and write to dest",
        "messages": [{"role": "user", "content": "Read source and write to dest"}],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "tool_approvals": {},
        "execution_status": RunStatus.RUNNING.value,
        "errors": [],
        "final_response": None,
    }

    # Invocation pauses for the write call only (read is auto)
    await graph.ainvoke(initial_state, config=config)

    snapshot = await graph.aget_state(config)
    assert bool(snapshot.next) is True

    pending = await app_service.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0].tool_call_id == "call_write_1"
    assert not (clean_workspace / "dest.txt").exists()

    # Approve write
    await app_service.record_decision(pending[0].id, "approved")
    final_state = await graph.ainvoke(Command(resume={"decision": "approved"}), config=config)

    assert final_state["execution_status"] == RunStatus.COMPLETED.value
    assert (clean_workspace / "dest.txt").exists()
    assert (clean_workspace / "dest.txt").read_text(encoding="utf-8") == "Dest Data"


@pytest.mark.asyncio
async def test_multi_tool_approved_write_and_rejected_write(test_db_session, clean_workspace, custom_registry):
    """
    Scenario 3: Approved Write 1 + Rejected Write 2.
    Write 1 executes; Write 2 is strictly blocked and never writes to disk.
    """
    app_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)
    mock_provider = MockModelProvider()
    router = ModelRouter(providers={"mock": mock_provider}, default_provider="mock")

    tc1 = ToolCallRequest(id="call_ok", name="write_workspace_file", arguments={"path": "ok.txt", "content": "OK"})
    tc2 = ToolCallRequest(id="call_deny", name="write_workspace_file", arguments={"path": "deny.txt", "content": "DENY"})
    mock_provider.queue_response(ModelResponse(content=None, tool_calls=[tc1, tc2], finish_reason="tool_calls"))
    mock_provider.queue_response(ModelResponse(content="Processed one ok, one rejected.", finish_reason="stop"))

    checkpointer = MemorySaver()
    graph = await get_compiled_graph(checkpointer=checkpointer)

    run_id = "run-appr-rej-1"
    config = {
        "configurable": {
            "thread_id": run_id,
            "memory_service": None,
            "approval_service": app_service,
            "trace_service": trace_service,
            "tool_registry": custom_registry,
            "model_router": router,
        }
    }

    initial_state = {
        "run_id": run_id,
        "session_id": "session-appr-rej",
        "user_message": "Write ok and deny files",
        "messages": [{"role": "user", "content": "Write ok and deny files"}],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "tool_approvals": {},
        "execution_status": RunStatus.RUNNING.value,
        "errors": [],
        "final_response": None,
    }

    # Pause on call_ok
    await graph.ainvoke(initial_state, config=config)
    app1 = (await app_service.get_pending_approvals())[0]
    assert app1.tool_call_id == "call_ok"

    # Approve call_ok
    await app_service.record_decision(app1.id, "approved")
    await graph.ainvoke(Command(resume={"decision": "approved"}), config=config)

    # Pause on call_deny
    app2 = (await app_service.get_pending_approvals())[0]
    assert app2.tool_call_id == "call_deny"

    # Reject call_deny
    await app_service.record_decision(app2.id, "rejected", decision_notes="Do not create deny.txt")
    final_state = await graph.ainvoke(Command(resume={"decision": "rejected", "decision_notes": "Do not create deny.txt"}), config=config)

    # Verify disk state: ok.txt MUST exist; deny.txt MUST NOT exist!
    assert (clean_workspace / "ok.txt").exists()
    assert (clean_workspace / "ok.txt").read_text(encoding="utf-8") == "OK"
    assert not (clean_workspace / "deny.txt").exists()

    # Check results in final state
    results = final_state["tool_results"]
    assert len(results) == 2
    res_ok = next(r for r in results if r["tool_call_id"] == "call_ok")
    res_deny = next(r for r in results if r["tool_call_id"] == "call_deny")
    assert res_ok["result"]["success"] is True
    assert res_deny["result"]["success"] is False
    assert res_deny["result"]["error_category"] == "approval_rejection"


@pytest.mark.asyncio
async def test_multi_tool_edited_first_write_while_second_unapproved(test_db_session, clean_workspace, custom_registry):
    """
    Scenario 4: Edited first write while second remains unapproved.
    Proves that while second write is unapproved, it does NOT execute.
    When resumed, first write uses edited arguments.
    """
    app_service = ApprovalService(test_db_session)
    trace_service = TraceService(test_db_session)
    mock_provider = MockModelProvider()
    router = ModelRouter(providers={"mock": mock_provider}, default_provider="mock")

    tc1 = ToolCallRequest(id="call_edit_1", name="write_workspace_file", arguments={"path": "original.txt", "content": "Original Content"})
    tc2 = ToolCallRequest(id="call_unappr_2", name="write_workspace_file", arguments={"path": "unapproved.txt", "content": "Unapproved Content"})
    mock_provider.queue_response(ModelResponse(content=None, tool_calls=[tc1, tc2], finish_reason="tool_calls"))
    mock_provider.queue_response(ModelResponse(content="Done.", finish_reason="stop"))

    checkpointer = MemorySaver()
    graph = await get_compiled_graph(checkpointer=checkpointer)

    run_id = "run-edit-unappr-1"
    config = {
        "configurable": {
            "thread_id": run_id,
            "memory_service": None,
            "approval_service": app_service,
            "trace_service": trace_service,
            "tool_registry": custom_registry,
            "model_router": router,
        }
    }

    initial_state = {
        "run_id": run_id,
        "session_id": "session-edit-unappr",
        "user_message": "Write original and unapproved",
        "messages": [{"role": "user", "content": "Write original and unapproved"}],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "tool_approvals": {},
        "execution_status": RunStatus.RUNNING.value,
        "errors": [],
        "final_response": None,
    }

    # First pause on call_edit_1
    await graph.ainvoke(initial_state, config=config)
    app1 = (await app_service.get_pending_approvals())[0]
    assert app1.tool_call_id == "call_edit_1"

    # Resume with edited arguments
    edited_args = {"path": "edited.txt", "content": "Super Safe Edited Content"}
    await app_service.record_decision(app1.id, "edited", edited_input=edited_args)
    await graph.ainvoke(Command(resume={"decision": "edited", "edited_input": edited_args}), config=config)

    # NOW AT THIS CRUCIAL INTERMEDIATE POINT:
    # Graph is paused waiting on the SECOND tool call (call_unappr_2)
    snapshot2 = await graph.aget_state(config)
    assert bool(snapshot2.next) is True

    pending2 = await app_service.get_pending_approvals()
    assert len(pending2) == 1
    assert pending2[0].tool_call_id == "call_unappr_2"

    # PROVE THAT THE UNAPPROVED SECOND WRITE HAS NOT EXECUTED:
    assert not (clean_workspace / "unapproved.txt").exists()

    # Reject second call to finalize run cleanly
    await app_service.record_decision(pending2[0].id, "rejected")
    final_state = await graph.ainvoke(Command(resume={"decision": "rejected"}), config=config)

    # PROVE:
    # 1. edited.txt exists with edited content
    assert (clean_workspace / "edited.txt").exists()
    assert (clean_workspace / "edited.txt").read_text(encoding="utf-8") == "Super Safe Edited Content"
    # 2. original.txt was never created
    assert not (clean_workspace / "original.txt").exists()
    # 3. unapproved.txt was never created
    assert not (clean_workspace / "unapproved.txt").exists()
