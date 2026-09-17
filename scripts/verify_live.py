"""Script to verify live end-to-end workflow on the local machine."""

import asyncio
import os
import uuid
from pathlib import Path
from httpx import ASGITransport, AsyncClient

from app.api.server import app
from app.core.settings import settings
from app.db.session import init_db
from app.orchestrator.graph import close_checkpointer, init_checkpointer


async def main():
    print("=" * 60)
    print("AURA LIVE VERTICAL SLICE VERIFICATION")
    print("=" * 60)

    # Initialize tables and checkpointer for standalone script run
    await init_db()
    await init_checkpointer()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Health check
        print("\n[Step 1] Checking /health...")
        res = await client.get("/health")
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 200

        # 2. Setup workspace file
        workspace = Path(settings.AURA_WORKSPACE_ROOT)
        workspace.mkdir(parents=True, exist_ok=True)
        sample_file = workspace / "demo_doc.txt"
        sample_file.write_text("AURA: Adaptive User Runtime Agent verified in production mode!", encoding="utf-8")
        output_file = workspace / "live_output.txt"
        output_file.unlink(missing_ok=True)
        print(f"\n[Step 2] Created sample file at {sample_file}")

        # 3. Request agent to read file (Automatic tool flow)
        session_id = f"live-demo-{uuid.uuid4().hex[:6]}"
        print(f"\n[Step 3] Sending chat query: 'Read demo_doc.txt' (Session: {session_id})...")
        chat_res = await client.post("/v1/chat", json={"session_id": session_id, "message": "Read demo_doc.txt"})
        print(f"Status: {chat_res.status_code}")
        read_data = chat_res.json()
        print(f"Agent Status: {read_data['status']}")
        print(f"Agent Response: {read_data['response']}")
        assert read_data["status"] == "completed"

        # 4. Request agent to write file (Approval pause flow)
        print("\n[Step 4] Sending chat query: 'Write Production Grade Agent to live_output.txt'...")
        write_res = await client.post(
            "/v1/chat",
            json={"session_id": session_id, "message": "Write Production Grade Agent to live_output.txt"},
        )
        write_data = write_res.json()
        print(f"Status: {write_res.status_code}")
        print(f"Agent Status: {write_data['status']}")
        print(f"Approval ID: {write_data['approval_id']}")
        assert write_data["status"] == "waiting_for_approval"

        output_file = workspace / "live_output.txt"
        print(f"Checking if file exists before approval: {output_file.exists()}")
        assert not output_file.exists()

        # 5. Inspect pending approvals
        print("\n[Step 5] Querying pending approvals...")
        appr_res = await client.get("/v1/approvals/pending")
        pending = appr_res.json()
        print(f"Found {len(pending)} pending approval(s). First tool: {pending[0]['tool_name']}")
        approval_id = write_data["approval_id"]

        # 6. Approve the pending action (Resume flow)
        print(f"\n[Step 6] Submitting approval for ID '{approval_id}'...")
        dec_res = await client.post(
            f"/v1/approvals/{approval_id}/decision",
            json={"decision": "approved", "decision_notes": "Live test manual confirmation."},
        )
        dec_data = dec_res.json()
        print(f"Status: {dec_res.status_code}")
        print(f"Resumed Run Status: {dec_data['execution_status']}")
        print(f"Final Response: {dec_data['final_response']}")
        assert dec_data["execution_status"] == "completed"

        # 7. Verify file was written
        print(f"Checking if file exists after approval: {output_file.exists()}")
        assert output_file.exists()
        print(f"File content: '{output_file.read_text(encoding='utf-8')}'")

        # 8. Path traversal attempt (Security boundary check)
        print("\n[Step 7] Testing security boundary: 'Read ../../outside.txt'...")
        sec_res = await client.post("/v1/chat", json={"session_id": session_id, "message": "Read ../../outside.txt"})
        sec_data = sec_res.json()
        print(f"Tool Result: {sec_data['tool_results'][0]['result']}")
        assert "ACCESS DENIED" in sec_data["tool_results"][0]["result"]["error"]

        # 9. Verify Run audit trace
        run_id = write_data["run_id"]
        print(f"\n[Step 8] Checking audit trace for write run '{run_id}'...")
        trace_res = await client.get(f"/v1/runs/{run_id}")
        trace_data = trace_res.json()
        print(f"Total events recorded: {len(trace_data['events'])}")
        for ev in trace_data["events"]:
            print(f" - [{ev['created_at']}] {ev['event_type']}")

    print("\n" + "=" * 60)
    print("ALL LIVE VERIFICATION STEPS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    await close_checkpointer()


if __name__ == "__main__":
    asyncio.run(main())
