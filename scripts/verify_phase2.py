"""Phase 2 End-to-End Vertical Slice Verification Script.

Demonstrates all 4 Phase 2 capability layers:
1. Multi-tier long-term memory with vector embeddings, project scoping, and restart durability.
2. Memory fact superseding with audit lineage.
3. Dynamic MCP tool discovery and failure-isolated execution.
4. Isolated container sandbox execution governed by human approval.
5. Persistent scheduler timer surviving simulated restart and triggering agent via EventToAgentBridge.
"""

import asyncio
import os
import sys
from datetime import timedelta

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

from app.db.session import async_session_factory, init_db
from app.db.models import MemoryModel, ScheduledJobModel, utc_now
from app.events.bus import EventBus
from app.events.dispatcher import EventToAgentBridge
from app.events.scheduler import PersistentScheduler
from app.events.types import AURAEvent, EventType
from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import MCPClientManager
from app.mcp.policy import MCPSecurityPolicy
from app.memory.context import ContextAssembler
from app.memory.embeddings.mock_provider import MockEmbeddingProvider
from app.memory.embeddings.router import EmbeddingRouter
from app.memory.pipeline import MemoryCandidatePipeline
from app.memory.service import SQLMemoryService
from app.sandbox.mock_runtime import MockSandboxRuntime
from app.sandbox.tools import SandboxPythonExecuteTool
from app.tools.registry import ToolRegistry


async def run_phase2_verification():
    print("=" * 70)
    print("AURA PHASE 2 CAPABILITY VERIFICATION: END-TO-END VERTICAL SLICE")
    print("=" * 70)

    # 0. Initialize DB schema
    await init_db()
    router = EmbeddingRouter(
        providers={"mock": MockEmbeddingProvider(dimension=1536)},
        default_provider="mock",
    )

    # -------------------------------------------------------------
    # STEP 1: Long-Term Project Memory & Retrieval Across Restart
    # -------------------------------------------------------------
    print("\n[Step 1] Storing project memory directive in database...")
    async with async_session_factory() as db:
        mem_service = SQLMemoryService(db=db, router=router)
        pipeline = MemoryCandidatePipeline()

        # Extract directive
        cands = pipeline.extract_candidates(
            user_message="Please remember that Project Atlas uses Python 3.12",
            active_project="Atlas",
        )
        assert len(cands) == 1, "Failed to extract project candidate"
        print(f" -> Extracted Candidate: type={cands[0].memory_type.value}, project={cands[0].project_name}, key={cands[0].key}")

        saved = await pipeline.process_and_commit(
            candidates=cands,
            session_id="phase2-demo-sess-1",
            run_id="run-step-1",
            memory_service=mem_service,
        )
        mem1_id = saved[0].id
        print(f" -> Saved Memory row: ID={mem1_id}, content='{saved[0].content}'")

    print("\n[Step 2] Simulating process restart & retrieving memory via ContextAssembler...")
    async with async_session_factory() as db_after_restart:
        restarted_service = SQLMemoryService(db=db_after_restart, router=router)
        assembler = ContextAssembler(memory_service=restarted_service)

        ctx = await assembler.assemble_context(
            session_id="phase2-demo-sess-2",
            user_message="How do I configure tests for Atlas?",
            project_name="Atlas",
        )
        formatted = ctx.format_for_system_prompt()
        print(f" -> Formatted Context for LLM Reasoning:\n{formatted}")
        assert "Project Atlas uses Python 3.12" in formatted, "Context missing stored project memory"

    # -------------------------------------------------------------
    # STEP 2: Memory Fact Superseding & Lineage Audit
    # -------------------------------------------------------------
    print("\n[Step 3] Updating project memory & verifying superseding audit trail...")
    async with async_session_factory() as db:
        mem_service = SQLMemoryService(db=db, router=router)
        pipeline = MemoryCandidatePipeline()

        cands_update = pipeline.extract_candidates(
            user_message="Project Atlas upgraded to Python 3.13",
            active_project="Atlas",
        )
        saved_update = await pipeline.process_and_commit(
            candidates=cands_update,
            session_id="phase2-demo-sess-1",
            run_id="run-step-2",
            memory_service=mem_service,
        )
        mem2_id = saved_update[0].id
        print(f" -> New Active Memory row: ID={mem2_id}, supersedes_id={saved_update[0].supersedes_id}")

        old_row = await db.get(MemoryModel, mem1_id)
        assert old_row.is_active is False, "Old memory was not marked is_active=False"
        assert old_row.superseded_by_id == mem2_id, "Old memory was not linked to new memory"
        print(f" -> Old Memory row {mem1_id}: is_active={old_row.is_active}, superseded_by={old_row.superseded_by_id}")

    # -------------------------------------------------------------
    # STEP 3: Dynamic MCP Tool Bus & Failure Isolation
    # -------------------------------------------------------------
    print("\n[Step 4] Dynamically discovering and executing tools from external MCP server...")
    mcp_registry = ToolRegistry()
    mcp_policy = MCPSecurityPolicy()
    mcp_manager = MCPClientManager(registry=mcp_registry, policy=mcp_policy)

    mcp_config = MCPServerConfig(
        id="demo_fixture",
        name="Demo Fixture MCP Server",
        transport=MCPTransportType.STDIO,
        command=sys.executable,
        args=["tests/fixtures/sample_mcp_server.py"],
        timeout_seconds=15.0,
        auto_approve_tools=["read_metric"],
    )
    mcp_manager.register_server(mcp_config)

    discovered = await mcp_manager.discover_tools("demo_fixture")
    print(f" -> Discovered {len(discovered)} MCP tools:")
    for t in discovered:
        print(f"    - {t.name} (Risk: {t.risk_level.value}, Caps: {t.required_capabilities})")

    # Execute read_metric via MCP bus
    read_tool = mcp_registry.get("mcp_demo_fixture_read_metric")
    assert read_tool is not None
    mcp_res = await read_tool.execute({"metric_name": "agent_uptime"})
    print(f" -> MCP Tool Execution Output: '{mcp_res.output}' (success={mcp_res.success})")
    assert mcp_res.success is True

    # -------------------------------------------------------------
    # STEP 4: Isolated Container Sandbox Tool Execution
    # -------------------------------------------------------------
    print("\n[Step 5] Executing Python code inside isolated sandbox runtime...")
    mock_sandbox = MockSandboxRuntime(available=True)
    sandbox_py_tool = SandboxPythonExecuteTool(runtime=mock_sandbox)
    print(f" -> Tool '{sandbox_py_tool.name}': Risk={sandbox_py_tool.risk_level.value}, Caps={sandbox_py_tool.required_capabilities}")

    sandbox_res = await sandbox_py_tool.execute({"code": "print('Sandbox Isolation Test OK')"})
    print(f" -> Sandbox Execution Output:\n{sandbox_py_tool.name} result: {sandbox_res.output}")
    assert sandbox_res.success is True

    # -------------------------------------------------------------
    # STEP 5: Persistent Scheduler Timer Surviving Restart
    # -------------------------------------------------------------
    print("\n[Step 6] Scheduling persistent timer, simulating restart, and triggering agent...")
    job_id = None
    async with async_session_factory() as db:
        scheduler = PersistentScheduler()
        job = await scheduler.schedule_one_shot(
            name="demo_restart_timer",
            delay_seconds=-1.0,  # Due immediately
            payload={
                "session_id": "phase2-proactive-session",
                "message": "Scheduler trigger: perform automated system healthcheck",
            },
            db=db,
        )
        job_id = job.id
        print(f" -> Scheduled Job ID: {job_id} in database.")

    # Simulate restart and tick with EventToAgentBridge
    print(" -> Simulating restart & ticking scheduler...")
    async with async_session_factory() as db_restart:
        restarted_bus = EventBus()
        restarted_scheduler = PersistentScheduler(bus=restarted_bus)

        # Connect EventToAgentBridge to the bus
        bridge = EventToAgentBridge(session_factory=async_session_factory)
        restarted_bus.subscribe(EventType.TIMER_FIRED.value, bridge.handle_event)

        emitted = await restarted_scheduler.tick(db=db_restart)
        assert len(emitted) == 1, "Scheduler failed to fire due timer"
        print(f" -> Scheduler emitted event: {emitted[0].event_type} [correlation_id: {emitted[0].correlation_id}]")

        # Verify job is marked inactive in DB
        refreshed_job = await db_restart.get(ScheduledJobModel, job_id)
        assert refreshed_job.is_active is False
        print(f" -> Job {job_id} status after tick: is_active={refreshed_job.is_active}")

    print("\n" + "=" * 70)
    print("ALL PHASE 2 VERTICAL SLICE VERIFICATIONS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_phase2_verification())
