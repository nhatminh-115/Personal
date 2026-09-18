"""Phase 2 End-to-End Vertical Slice Live Verification Script.

Exercises real FastAPI HTTP endpoints (/v1/chat, /v1/approvals) and core Phase 2 capabilities:
1. Multi-tier long-term memory with project scoping & isolation through /v1/chat.
2. Live MCP read tool auto-execution through /v1/chat without human pause.
3. Live MCP mutating tool triggering LangGraph interrupt, approving via /v1/approvals/{id}/decision, and resuming.
4. Sandbox execution with bounded output limits.
5. Durable transactional outbox publication, atomic claiming, and OutboxWorker processing.
"""

import asyncio
import os
import sys
import httpx

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath("."))

# Configure isolated verification database
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///aura_verify.db"
os.environ["CHECKPOINT_DB_PATH"] = "./aura_verify_checkpoints.db"

# Remove any previous verification artifacts
for p in ["aura_verify.db", "aura_verify_checkpoints.db"]:
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass

from app.api.server import create_app, lifespan
from app.db.models import EventRecordModel
from app.db.session import async_session_factory, init_db
from app.events.bus import EventBus
from app.events.types import AURAEvent, EventType
from app.events.worker import OutboxWorker
from app.mcp.config import MCPServerConfig, MCPTransportType
from app.mcp.manager import mcp_manager
from app.orchestrator.graph import close_checkpointer
from app.sandbox.docker_runtime import DockerSandboxRuntime
from app.sandbox.mock_runtime import MockSandboxRuntime
from app.sandbox.spec import SandboxConfig
from app.sandbox.tools import SandboxPythonExecuteTool


async def run_phase2_verification():
    print("=" * 75, flush=True)
    print("AURA PHASE 2.1 VERIFICATION: END-TO-END VERTICAL SLICE THROUGH REAL API", flush=True)
    print("=" * 75, flush=True)

    app = create_app()

    try:
        async with lifespan(app):
            # Register sample MCP server
            mcp_config = MCPServerConfig(
                id="sample-mcp",
                name="Sample MCP Server",
                transport=MCPTransportType.STDIO,
                command=sys.executable,
                args=["tests/fixtures/sample_mcp_server.py"],
                auto_approve_tools=["read_metric", "system_echo"],
                timeout_seconds=10.0,
            )
            mcp_manager.register_server(mcp_config)
            discovered = await mcp_manager.discover_tools("sample-mcp")
            print(f"\n[MCP Setup] Discovered {len(discovered)} tools from MCP server:", flush=True)
            for t in discovered:
                print(f"  - {t.name} (Risk: {t.risk_level.value}, Caps: {t.required_capabilities})", flush=True)

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60.0) as client:

                # -------------------------------------------------------------
                # STEP 1: Project Memory Isolation through /v1/chat
                # -------------------------------------------------------------
                print("\n[Step 1] Project-isolated memory write and retrieval via /v1/chat...", flush=True)
                # 1a. Store memory directive under Atlas
                write_resp = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-atlas-1",
                        "project_name": "Atlas",
                        "message": "Please remember that Project Atlas uses Python 3.12",
                    },
                )
                assert write_resp.status_code == 200, f"Write failed: {write_resp.text}"
                write_data = write_resp.json()
                assert write_data["status"] == "completed"
                print(" -> Stored fact for 'Atlas' successfully.", flush=True)

                # 1b. Retrieve under Atlas in a new session
                query_atlas = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-atlas-2",
                        "project_name": "Atlas",
                        "message": "What version of Python does the project use?",
                    },
                )
                assert query_atlas.status_code == 200
                atlas_data = query_atlas.json()
                assert "Python 3.12" in atlas_data["response"], f"Expected Python 3.12 in response: {atlas_data['response']}"
                print(f" -> Atlas Query Response: '{atlas_data['response']}' (Memory successfully injected)", flush=True)

                # 1c. Verify isolation: Boreas must NOT see Atlas memory
                query_boreas = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-boreas-1",
                        "project_name": "Boreas",
                        "message": "What version of Python does the project use?",
                    },
                )
                assert query_boreas.status_code == 200
                boreas_data = query_boreas.json()
                assert "Python 3.12" not in boreas_data["response"], "Leak detected: Boreas accessed Atlas memory!"
                print(f" -> Boreas Query Response: '{boreas_data['response']}' (Isolation verified: Atlas memory withheld)", flush=True)

                # -------------------------------------------------------------
                # STEP 2: Live MCP Read Tool Auto-Execution via /v1/chat
                # -------------------------------------------------------------
                print("\n[Step 2] Live MCP Read Tool execution (auto-approved) via /v1/chat...", flush=True)
                mcp_read_resp = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-mcp-read",
                        "message": "Read metric system_health_ratio",
                    },
                )
                assert mcp_read_resp.status_code == 200
                mcp_read_data = mcp_read_resp.json()
                assert mcp_read_data["status"] == "completed"
                assert mcp_read_data["approval_id"] is None
                assert "system_health_ratio" in mcp_read_data["response"]
                assert "99.9%" in mcp_read_data["response"]
                print(f" -> MCP Read Tool Response: '{mcp_read_data['response']}' (Executed automatically)", flush=True)

                # -------------------------------------------------------------
                # STEP 3: Live MCP Mutation Tool Interrupt & Approval Resume
                # -------------------------------------------------------------
                print("\n[Step 3] Live MCP Mutation Tool pausing for approval and resuming via API...", flush=True)
                mutate_resp = await client.post(
                    "/v1/chat",
                    json={
                        "session_id": "sess-mcp-mutate",
                        "message": "Mutate record user_rec_100 to tier_premium",
                    },
                )
                assert mutate_resp.status_code == 200
                mutate_data = mutate_resp.json()
                assert mutate_data["status"] == "waiting_for_approval"
                approval_id = mutate_data["approval_id"]
                assert approval_id is not None
                print(f" -> Execution Suspended. Approval ID: {approval_id}", flush=True)

                # Inspect pending approval
                get_appr = await client.get(f"/v1/approvals/{approval_id}")
                assert get_appr.status_code == 200
                appr_info = get_appr.json()
                assert appr_info["tool_name"] == "mcp_sample-mcp_mutate_record"
                assert appr_info["risk_level"].lower() == "high"
                assert appr_info["status"] == "pending"
                print(f" -> Pending Approval details verified: tool={appr_info['tool_name']}, risk={appr_info['risk_level']}", flush=True)

                # Submit approval decision
                dec_resp = await client.post(
                    f"/v1/approvals/{approval_id}/decision",
                    json={"decision": "approved", "decision_notes": "Approved by SecOps"},
                )
                assert dec_resp.status_code == 200
                dec_data = dec_resp.json()
                assert dec_data["status"] == "approved"
                assert dec_data["execution_status"] == "completed"
                assert "Record user_rec_100 updated to tier_premium" in dec_data["final_response"]
                print(f" -> Resume Completed! Final Response: '{dec_data['final_response']}'", flush=True)

                # -------------------------------------------------------------
                # STEP 4: Sandbox Execution (Real Docker on CI / Mock Fallback)
                # -------------------------------------------------------------
                print("\n[Step 4] Sandbox execution with bounded output enforcement...", flush=True)
                docker_runtime = DockerSandboxRuntime()
                docker_available = docker_runtime.is_available()
                is_ci = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

                if not docker_available:
                    if is_ci:
                        raise RuntimeError("Docker daemon is required on CI for production sandbox verification, but is unavailable!")
                    else:
                        print(" [NOTICE] Docker daemon is unavailable in local environment — skipping real Docker acceptance slice (CI will enforce).", flush=True)
                        cfg = SandboxConfig(max_output_bytes=1024)
                        mock_runtime = MockSandboxRuntime(available=True, config=cfg)
                        sandbox_tool = SandboxPythonExecuteTool(runtime=mock_runtime)
                        large_code = "# " + ("A" * 2000)
                        res = await sandbox_tool.execute({"code": large_code})
                        assert res.success is True
                        assert "exceeded max_output_bytes limit" in res.output
                        print(f" -> Local Mock Sandbox bounded output test verified. Output length: {len(res.output)} bytes", flush=True)
                else:
                    print(" -> Docker daemon detected! Executing real Docker vertical slice through /v1/chat...", flush=True)
                    # 4a. Request Python execution in sandbox via /v1/chat
                    docker_chat_resp = await client.post(
                        "/v1/chat",
                        json={
                            "session_id": "sess-docker-1",
                            "message": "Execute python in sandbox: print('AURA_DOCKER_SUCCESS_99')",
                        },
                    )
                    assert docker_chat_resp.status_code == 200, f"Chat request failed: {docker_chat_resp.text}"
                    docker_chat_data = docker_chat_resp.json()
                    assert docker_chat_data["status"] == "waiting_for_approval", f"Expected waiting_for_approval, got {docker_chat_data['status']}"
                    docker_approval_id = docker_chat_data["approval_id"]
                    assert docker_approval_id is not None
                    print(f" -> LangGraph suspended for Docker approval. Approval ID: {docker_approval_id}", flush=True)

                    # 4b. Inspect approval
                    appr_resp = await client.get(f"/v1/approvals/{docker_approval_id}")
                    assert appr_resp.status_code == 200
                    appr_data = appr_resp.json()
                    assert appr_data["tool_name"] == "sandbox_python_execute"
                    assert appr_data["risk_level"].lower() == "high"
                    print(f" -> Approval verified: tool={appr_data['tool_name']}, risk={appr_data['risk_level']}", flush=True)

                    # 4c. Approve tool call and resume SAME graph
                    dec_resp = await client.post(
                        f"/v1/approvals/{docker_approval_id}/decision",
                        json={"decision": "approved", "decision_notes": "SecOps authorized Docker execution"},
                    )
                    assert dec_resp.status_code == 200, f"Decision failed: {dec_resp.text}"
                    dec_data = dec_resp.json()
                    assert dec_data["status"] == "approved"
                    assert dec_data["execution_status"] == "completed"
                    assert "AURA_DOCKER_SUCCESS_99" in dec_data["final_response"], f"Expected docker output in response: {dec_data['final_response']}"
                    print(f" -> Real Docker execution succeeded! Final Agent Response: '{dec_data['final_response']}'", flush=True)

                    # 4d. Verify bounded output against real Docker runtime
                    print(" -> Testing bounded output limit against real Docker container...", flush=True)
                    bounded_cfg = SandboxConfig(max_output_bytes=2048, timeout_seconds=15.0)
                    bounded_res = await docker_runtime.run_python('print("DOCKER_BOUNDED_" * 500)', config=bounded_cfg)
                    assert bounded_res.exit_code == 0
                    assert bounded_res.metadata.get("truncated") is True
                    assert "Output truncated" in bounded_res.stdout
                    print(f" -> Bounded output verified on real Docker! Output bytes: {len(bounded_res.stdout)}", flush=True)

        # -------------------------------------------------------------
        # STEP 5: Durable Outbox & OutboxWorker Processing
        # -------------------------------------------------------------
        print("\n[Step 5] Durable Outbox publication, atomic claim, and worker delivery...", flush=True)
        bus = EventBus()
        worker = OutboxWorker(bus=bus, worker_id="verify-worker-1")

        delivered_events = []
        bus.subscribe(EventType.TIMER_FIRED.value, lambda evt: delivered_events.append(evt))

        async with async_session_factory() as db:
            test_event = AURAEvent(
                event_type=EventType.TIMER_FIRED.value,
                payload={"task": "hourly_maintenance", "code": 200},
                source="scheduler_verify",
                correlation_id="corr-outbox-verify-01",
                idempotency_key="idemp-verify-001",
            )
            published_event = await bus.publish(test_event, db=db)
            print(f" -> Outbox Event committed to DB: ID={published_event.id}, status={published_event.status.value}", flush=True)
            assert published_event.status.value == "pending"

            # Worker processes the outbox batch
            processed_count = await worker.process_outbox_batch(db=db, batch_size=5)
            assert processed_count == 1
            print(f" -> OutboxWorker processed {processed_count} event(s)", flush=True)

            # Verify DB status updated to processed
            updated_rec = await db.get(EventRecordModel, test_event.id)
            assert updated_rec.status == "processed"
            assert len(delivered_events) == 1
            assert delivered_events[0].payload["task"] == "hourly_maintenance"
            print(f" -> Outbox Event ID {test_event.id} successfully transitioned to '{updated_rec.status}'", flush=True)

        print("\n" + "=" * 75, flush=True)
        print("ALL PHASE 2.1 VERTICAL SLICE VERIFICATIONS COMPLETED SUCCESSFULLY!", flush=True)
        print("=" * 75, flush=True)

    finally:
        # Guarantee comprehensive cleanup of verification resources
        try:
            await mcp_manager.disconnect_all()
        except Exception:
            pass
        try:
            await close_checkpointer()
        except Exception:
            pass
        for p in ["aura_verify.db", "aura_verify_checkpoints.db"]:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(run_phase2_verification(), timeout=90.0))
