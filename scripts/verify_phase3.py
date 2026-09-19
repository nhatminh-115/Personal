"""Phase 3 Multi-Step Agent Runtime & Controlled Specialist Delegation Live Verification Script.

Exercises real FastAPI HTTP endpoints (/v1/chat, /v1/approvals) and core Phase 3 capabilities:
1. Preflight Project Memory exact match lookup (resistance against SQL wildcard collision).
2. Milestone 3A: Iterative Agent Execution Loop & Bounded Controls (deadline, failures, steps).
3. Milestone 3B: Deterministic Task / Model Routing Policy with Capability & Privacy Matching.
4. Milestone 3C & 3D: Controlled Specialist Delegation, Scoped Tool Registries, and Anti-Swarm Recursion Guard.
5. Milestone 3E: Full Vertical Slice — Personal Orchestrator delegates "Fix the failing test in project Atlas"
   to Coding Specialist (inspect -> test fail Docker -> edit file with approval -> resume -> test pass Docker -> report to root).
"""

import asyncio
import os
import shutil
import sys
from pathlib import Path
import httpx
from sqlalchemy import select

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

# Configure isolated verification database
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///aura_verify_p3.db"
os.environ["CHECKPOINT_DB_PATH"] = "./aura_verify_p3_checkpoints.db"
os.environ["MODEL_PROVIDER"] = "mock"

# Remove any previous verification artifacts
for p in ["aura_verify_p3.db", "aura_verify_p3_checkpoints.db"]:
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass

from app.api.server import create_app, lifespan
from app.core.settings import settings
from app.db.models import DelegationModel, RunEventModel, RunModel
from app.db.session import async_session_factory
from app.delegation.registry import specialist_registry
from app.delegation.runtime import delegation_runtime
from app.delegation.types import DelegationRequest
from app.memory.service import SQLMemoryService
from app.models.base import RoutingContext
from app.models.mock_provider import MockModelProvider
from app.models.router import model_router
from app.models.routing_policy import DeterministicRoutingPolicy, ProviderMetadata
from app.orchestrator.graph import close_checkpointer
from app.tools.registry import tool_registry
from app.tools.scoped import ScopedToolRegistry


async def run_phase3_verification():
    print("=" * 80, flush=True)
    print("AURA PHASE 3 VERIFICATION: MULTI-STEP AGENT RUNTIME & SPECIALIST DELEGATION", flush=True)
    print("=" * 80, flush=True)

    app = create_app()
    verify_workspace = Path("./aura_verify_workspace").resolve()
    if verify_workspace.exists():
        shutil.rmtree(verify_workspace)
    verify_workspace.mkdir(parents=True, exist_ok=True)

    original_ws = settings.AURA_WORKSPACE_ROOT
    settings.AURA_WORKSPACE_ROOT = verify_workspace

    try:
        async with lifespan(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60.0) as client:

                # -------------------------------------------------------------
                # STEP 1: Preflight Project Memory Exact Lookup Resistance
                # -------------------------------------------------------------
                print("\n[Step 1] Preflight: Verifying Project Memory exact lookup resistance against wildcards...", flush=True)
                async with async_session_factory() as db:
                    mem_svc = SQLMemoryService(db)
                    await mem_svc.store_project_memory("Atlas_Core", "fact_a", "Fact A: Underscore project")
                    await mem_svc.store_project_memory("AtlasXCore", "fact_b", "Fact B: Regular project")
                    await mem_svc.store_project_memory("Atlas%Core", "fact_c", "Fact C: Percent project")

                    mem_under = await mem_svc.get_project_memories("Atlas_Core")
                    assert len(mem_under) == 1
                    assert mem_under[0].content == "Fact A: Underscore project"

                    mem_pct = await mem_svc.get_project_memories("Atlas%Core")
                    assert len(mem_pct) == 1
                    assert mem_pct[0].content == "Fact C: Percent project"
                    print(" -> Exact lookup verified: wildcard characters ('%', '_') do not cause cross-project collisions.", flush=True)

                # -------------------------------------------------------------
                # STEP 2: Milestone 3B Model Routing Policy Verification
                # -------------------------------------------------------------
                print("\n[Step 2] Milestone 3B: Verifying Deterministic Task & Model Routing Policy...", flush=True)
                policy = DeterministicRoutingPolicy()
                meta_registry = {
                    "mock": ProviderMetadata(
                        name="mock",
                        capabilities=["general", "code", "reasoning", "fast", "local"],
                        privacy_status="local",
                        default_model="mock-default",
                    ),
                    "cloud-code": ProviderMetadata(
                        name="cloud-code",
                        capabilities=["code", "general"],
                        privacy_status="cloud",
                        default_model="code-expert-v1",
                        models=["code-expert-v1", "custom-weights"],
                    ),
                    "cloud-reasoning": ProviderMetadata(
                        name="cloud-reasoning",
                        capabilities=["reasoning", "general"],
                        privacy_status="cloud",
                        default_model="reasoning-deep-o1",
                    ),
                }

                # 2a. Explicit override
                sel_override = policy.select(
                    context=RoutingContext(explicit_model_override="cloud-code:custom-weights"),
                    available_metadata=meta_registry,
                    default_provider="mock",
                )
                assert sel_override.provider_name == "cloud-code"
                assert sel_override.model_name == "custom-weights"

                # 2a-ii. Unsupported model on known provider raises loudly
                try:
                    policy.select(
                        context=RoutingContext(explicit_model_override="cloud-code:nonexistent-model"),
                        available_metadata=meta_registry,
                        default_provider="mock",
                    )
                    raise AssertionError("Expected ValueError for unsupported model on known provider!")
                except ValueError as err:
                    assert "is not supported by provider 'cloud-code'" in str(err)

                # 2b. Privacy confidential requirement
                sel_conf = policy.select(
                    context=RoutingContext(task_type="coding", privacy_requirement="confidential"),
                    available_metadata=meta_registry,
                    default_provider="cloud-code",
                )
                assert sel_conf.provider_name == "mock"
                assert "confidential" in sel_conf.reason.lower()

                # 2c. Coding specialization
                sel_code = policy.select(
                    context=RoutingContext(task_type="coding"),
                    available_metadata=meta_registry,
                    default_provider="mock",
                )
                assert sel_code.provider_name in {"cloud-code", "mock"}

                print(" -> Model routing policy successfully verified across explicit, privacy, and capability rules.", flush=True)

                # -------------------------------------------------------------
                # STEP 3: Milestone 3C & 3D Scoped Tools & Anti-Swarm Guard
                # -------------------------------------------------------------
                print("\n[Step 3] Milestone 3C & 3D: Verifying Scoped Tools and Recursion Prevention...", flush=True)
                coding_spec = specialist_registry.get("coding")
                assert coding_spec is not None

                # 3a. Whitelist and blocked delegate_task
                scoped = ScopedToolRegistry(tool_registry, coding_spec.allowed_tools)
                assert "delegate_task" not in scoped.allowed_tool_names
                assert "read_workspace_file" in scoped.allowed_tool_names
                assert "write_workspace_file" in scoped.allowed_tool_names

                # 3b. Specialist-to-specialist recursion prevention
                async with async_session_factory() as db:
                    re_req = DelegationRequest(
                        specialist_name="coding",
                        task_description="Infinite recursion attempt",
                        context={"is_specialist": True, "specialist_name": "subagent_1"},
                        parent_run_id="run-p-1",
                        session_id="sess-rec-1",
                    )
                    from app.core.errors import PermissionError
                    try:
                        await delegation_runtime.delegate(re_req, db=db)
                        assert False, "Should have raised PermissionError"
                    except PermissionError:
                        print(" -> Anti-swarm guard verified: specialists are strictly blocked from re-delegating.", flush=True)

                # -------------------------------------------------------------
                # STEP 4: Milestone 3A Iterative Execution Loop & Bounded Controls
                # -------------------------------------------------------------
                print("\n[Step 4] Milestone 3A: Bounded controls enforcement (max consecutive failures limit)...", flush=True)
                mock = model_router.get_provider("mock")
                assert isinstance(mock, MockModelProvider)
                mock.clear_queue()
                from app.models.base import ModelResponse, ToolCallRequest
                for i in range(3):
                    mock.queue_response(
                        ModelResponse(
                            content="Reading non-existent...",
                            tool_calls=[ToolCallRequest(id=f"fail_{i}", name="read_workspace_file", arguments={"path": f"non_existent_{i}.txt"})],
                            finish_reason="tool_calls",
                        )
                    )

                resp_fail = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-bounds-test",
                        "message": "Trigger failures",
                        "metadata": {"max_consecutive_failures": 2},
                    },
                )
                assert resp_fail.status_code == 200
                data_fail = resp_fail.json()
                assert data_fail["status"] == "failed"
                assert "consecutive tool failures" in data_fail["response"]
                print(" -> Bounded execution control verified: agent halts when consecutive failure budget is exhausted.", flush=True)

                # -------------------------------------------------------------
                # STEP 5: Milestone 3E First Coding Specialist Vertical Slice
                # -------------------------------------------------------------
                print("\n[Step 5] Milestone 3E: Full End-to-End Vertical Slice — 'Fix the failing test in project Atlas'...", flush=True)
                mock.clear_queue()
                # 5a. Create project files with failing bug
                calc_code = verify_workspace / "calculator.py"
                calc_code.write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
                calc_test = verify_workspace / "test_calculator.py"
                calc_test.write_text(
                    "from calculator import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
                    encoding="utf-8",
                )
                print(" -> Seeded Atlas workspace with failing test (1 + 2 = 4 != 3).", flush=True)

                # 5b. Personal Orchestrator triggers delegation
                chat_resp = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-atlas-live-p3",
                        "message": "Fix the failing test in project Atlas",
                        "project_name": "Atlas",
                    },
                )
                assert chat_resp.status_code == 200
                chat_data = chat_resp.json()
                assert chat_data["status"] == "waiting_for_approval"
                approval_id = chat_data["approval_id"]
                assert approval_id is not None
                parent_run_id = chat_data["run_id"]
                print(f" -> LangGraph suspended for code-edit approval. Approval ID: {approval_id}", flush=True)

                # 5c. Approval 1: Human Operator authorizes initial test execution (sandbox_shell_execute)
                appr1_inspect = await client.get(f"/v1/approvals/{approval_id}")
                assert appr1_inspect.status_code == 200
                appr1_data = appr1_inspect.json()
                assert appr1_data["tool_name"] == "sandbox_shell_execute"
                print(f" -> Approval 1 (Initial Sandbox Test): tool={appr1_data['tool_name']}, risk={appr1_data['risk_level']}", flush=True)

                dec1_resp = await client.post(
                    f"/v1/approvals/{approval_id}/decision",
                    json={"decision": "approved", "decision_notes": "Operator authorized initial test execution in sandbox"},
                )
                assert dec1_resp.status_code == 200
                dec1_data = dec1_resp.json()
                assert dec1_data["status"] == "approved"
                assert dec1_data["execution_status"] == "waiting_for_approval"
                approval2_id = dec1_data["approval_id"]
                assert approval2_id is not None
                assert approval2_id != approval_id

                # 5d. Approval 2: Human Operator authorizes file patch (write_workspace_file)
                appr2_inspect = await client.get(f"/v1/approvals/{approval2_id}")
                assert appr2_inspect.status_code == 200
                appr2_data = appr2_inspect.json()
                assert appr2_data["tool_name"] == "write_workspace_file"
                print(f" -> Approval 2 (Workspace Code Patch): tool={appr2_data['tool_name']}, risk={appr2_data['risk_level']}", flush=True)

                dec2_resp = await client.post(
                    f"/v1/approvals/{approval2_id}/decision",
                    json={"decision": "approved", "decision_notes": "Operator authorized calculator.py bugfix patch"},
                )
                assert dec2_resp.status_code == 200
                dec2_data = dec2_resp.json()
                assert dec2_data["status"] == "approved"
                assert dec2_data["execution_status"] == "waiting_for_approval"
                approval3_id = dec2_data["approval_id"]
                assert approval3_id is not None
                assert approval3_id != approval2_id

                # 5e. Approval 3: Human Operator authorizes verification test run (sandbox_shell_execute)
                appr3_inspect = await client.get(f"/v1/approvals/{approval3_id}")
                assert appr3_inspect.status_code == 200
                appr3_data = appr3_inspect.json()
                assert appr3_data["tool_name"] == "sandbox_shell_execute"
                print(f" -> Approval 3 (Verification Sandbox Test): tool={appr3_data['tool_name']}, risk={appr3_data['risk_level']}", flush=True)

                dec3_resp = await client.post(
                    f"/v1/approvals/{approval3_id}/decision",
                    json={"decision": "approved", "decision_notes": "Operator authorized verification test run in sandbox"},
                )
                assert dec3_resp.status_code == 200
                dec3_data = dec3_resp.json()
                assert dec3_data["status"] == "approved"
                assert dec3_data["execution_status"] == "completed"
                print(" -> Resumed run completed successfully with verified 3-approval semantics!", flush=True)

                # 5f. Verify Code Mutation in Workspace
                patched_code = calc_code.read_text(encoding="utf-8")
                assert "return a + b" in patched_code
                assert "+ 1" not in patched_code
                print(" -> Workspace verification: calculator.py has been patched accurately.", flush=True)

                # 5g. Verify Database Lineage: Parent & Child Runs & Delegation Record
                async with async_session_factory() as db:
                    runs_res = await db.execute(
                        select(RunModel).where(RunModel.session_id == "sess-atlas-live-p3").order_by(RunModel.created_at.asc())
                    )
                    all_runs = list(runs_res.scalars().all())
                    assert len(all_runs) >= 2

                    parent = next((r for r in all_runs if r.id == parent_run_id), None)
                    assert parent is not None
                    assert parent.parent_run_id is None
                    assert parent.status == "completed"

                    child = next((r for r in all_runs if r.parent_run_id == parent_run_id), None)
                    assert child is not None
                    assert child.status == "completed"
                    assert "[Specialist: coding]" in child.user_message

                    # Verify Delegation Table record
                    del_res = await db.execute(
                        select(DelegationModel).where(DelegationModel.parent_run_id == parent.id)
                    )
                    delegations = list(del_res.scalars().all())
                    assert len(delegations) == 1
                    assert delegations[0].child_run_id == child.id
                    assert delegations[0].status == "completed"

                    # 5h. Verify Audit Trace Events
                    parent_events_res = await db.execute(select(RunEventModel).where(RunEventModel.run_id == parent.id))
                    p_ev_types = [e.event_type for e in parent_events_res.scalars().all()]
                    assert "delegation_started" in p_ev_types
                    assert "delegation_completed" in p_ev_types

                    child_events_res = await db.execute(select(RunEventModel).where(RunEventModel.run_id == child.id))
                    c_ev_types = [e.event_type for e in child_events_res.scalars().all()]
                    assert "request_received" in c_ev_types
                    assert "step_completed" in c_ev_types
                    assert "approval_requested" in c_ev_types

                    print(f" -> DB Lineage & Audit Trail verified: Parent Run '{parent.id}' <-> Child Run '{child.id}', Delegation Record intact", flush=True)

        print("\n" + "=" * 80, flush=True)
        print("PHASE 3 VERIFICATION PASSED: ALL 5 MILESTONES ACCEPTED SUCCESSFULLY", flush=True)
        print("=" * 80, flush=True)

    finally:
        settings.AURA_WORKSPACE_ROOT = original_ws
        if verify_workspace.exists():
            shutil.rmtree(verify_workspace, ignore_errors=True)
        await close_checkpointer()
        for p in ["aura_verify_p3.db", "aura_verify_p3_checkpoints.db"]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(run_phase3_verification(), timeout=90.0))
