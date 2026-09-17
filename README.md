# AURA — Adaptive User Runtime Agent

> **Production-grade personal AI agent runtime with persistent memory, capability-based security, durable LangGraph orchestration, and native human-in-the-loop authorization.**

---

## Architecture Overview

AURA is designed as a stateful, predictable operating process rather than an ephemeral completion chatbot. 

```
                                      +---------------------------------------------+
                                      |            FastAPI Gateway (/v1)            |
                                      +---------------------------------------------+
                                                             |
                                                             v
+------------------------+             +---------------------------------------------+
|    PostgreSQL 16       |<----------->|        LangGraph Personal Orchestrator      |
|  (Memory, Runs, Trace) |             |  (Checkpointer: AsyncSqliteSaver / Memory)   |
+------------------------+             +---------------------------------------------+
                                                |                   |             |
                                                v                   v             v
                                     +--------------------+ +---------------+ +------------------+
                                     | ModelRouter (LLM)  | | MemoryService | | CapabilityEngine |
                                     | (OpenAI/Mock/Local)| | (5-Tier Store)| | & Approval Layer |
                                     +--------------------+ +---------------+ +------------------+
                                                                                  |
                                                                                  v
                                                                      +-----------------------+
                                                                      | Tool Runtime & Sandbox|
                                                                      | (Strict Path Jail)    |
                                                                      +-----------------------+
```

### Core Subsystems

1. **Personal Orchestrator (LangGraph):**
   - Pure state machine compiling discrete nodes: `load_context` -> `reason` -> `route_decision` -> `execute_tool` -> `verify_result` -> `update_memory`.
   - **Durable Interruption:** High-risk actions call `interrupt()`, persisting state to `AsyncSqliteSaver`. Restarts survive seamlessly; resumes happen via `Command(resume=...)` by `thread_id=run_id`.
   - **Canonical Message Schema:** True multi-turn conversation turns (`system`, `user`, `assistant(tool_calls=...)`, `tool(tool_call_id=...)`, `assistant`).

2. **Multi-Tier Memory Architecture:**
   - **Working Memory:** Active session conversation history and turn state.
   - **Episodic Memory:** Structured chronological summaries of past turns and tool executions.
   - **Semantic Memory:** Declarative knowledge base with vector embeddings (`pgvector`).
   - **Profile Memory:** Persistent user preferences and identity facts.
   - **Project Memory:** Contextual facts scoped to specific workspaces.

3. **Capability & Human-in-the-Loop Approval:**
   - Tools declare required capabilities (`filesystem.read`, `filesystem.write`, `shell.execute`).
   - Low-risk read actions execute automatically; high-risk write/mutation actions trigger approval.
   - Idempotent approval creation and single-terminal event guarantee.

4. **Hardened Workspace Sandbox:**
   - Confined strictly to `AURA_WORKSPACE_ROOT`.
   - Rejects null bytes (`\0`), absolute path escapes, nested traversals (`../../`), and Windows junction/symlink escapes.

5. **Observability & Audit Tracing:**
   - Granular event timeline (`run_events` table) tracking `request_received`, `context_loaded`, `model_called`, `approval_requested`, `approval_granted`, `tool_executed`, `response_generated`, `memory_updated`, `run_completed`.
   - Explicit failure categorization: `tool_failure`, `provider_failure`, `permission_failure`, `approval_rejection`, `graph_failure`.

---

## Quickstart & Setup

### Prerequisites
- Python 3.11+ (Python 3.12 recommended)
- PostgreSQL with `pgvector` extension (or automatic local SQLite fallback for dev/testing)

### Installation
```powershell
# Clone repository
git clone https://github.com/nhatminh-115/Personal.git aura
cd aura

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -e .
```

### Configuration
Create or modify `.env`:
```env
AURA_DATABASE_URL=sqlite+aiosqlite:///./aura.db
AURA_WORKSPACE_ROOT=./workspace
DEFAULT_MODEL_PROVIDER=mock  # or openai
OPENAI_API_KEY=your-api-key-here
```

---

## Running the Server

Start the FastAPI application with Uvicorn:
```powershell
$env:PYTHONPATH="."
uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
```

Interactive OpenAPI documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Running Tests

Run the complete test suite:
```powershell
pytest -v
```

Run specific test categories:
```powershell
# Unit tests
pytest tests/unit/ -v

# Integration tests (including restart durability across processes)
pytest tests/integration/ -v

# End-to-end flows
pytest tests/e2e/ -v
```

Run live vertical slice verification (Phase 1):
```powershell
$env:PYTHONPATH="."
python scripts/verify_live.py
```

Run Phase 2 capability verification (Memory, MCP, Docker Sandbox, Event Scheduler):
```powershell
$env:PYTHONPATH="."
python scripts/verify_phase2.py
```

---

## API Usage Examples (cURL)

### 1. Direct Chat (Automatic Tool Execution)
Request the agent to read a file inside the workspace:
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "session-1", "message": "Read notes.txt"}'
```
Response:
```json
{
  "run_id": "8f39575e-...",
  "session_id": "session-1",
  "response": "Based on the tool output: ...",
  "status": "completed",
  "approval_id": null
}
```

### 2. High-Risk Action (Suspension for Approval)
Request the agent to write a file to the workspace:
```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "session-1", "message": "Write Hello World to hello.txt"}'
```
Response (Agent halts execution and checkpoints state):
```json
{
  "run_id": "ef3b5bb3-...",
  "session_id": "session-1",
  "response": "Action requires human approval before execution.",
  "status": "waiting_for_approval",
  "approval_id": "3ec064f4-..."
}
```

### 3. Inspect Pending Approvals
```bash
curl -X GET http://localhost:8000/v1/approvals/pending
```

### 4. Approve, Reject, or Edit and Resume Execution
Resumes the suspended LangGraph execution from the exact SQLite checkpoint via `POST /v1/approvals/{approval_id}/decision`:

**Approve:**
```bash
curl -X POST http://localhost:8000/v1/approvals/3ec064f4-.../decision \
  -H "Content-Type: application/json" \
  -d '{"decision": "approved", "decision_notes": "Approved by developer"}'
```

**Reject:**
```bash
curl -X POST http://localhost:8000/v1/approvals/3ec064f4-.../decision \
  -H "Content-Type: application/json" \
  -d '{"decision": "rejected", "decision_notes": "Denied by user"}'
```

**Edit Input:**
```bash
curl -X POST http://localhost:8000/v1/approvals/3ec064f4-.../decision \
  -H "Content-Type: application/json" \
  -d '{"decision": "edited", "edited_input": {"path": "hello.txt", "content": "Edited Hello World"}}'
```

Response:
```json
{
  "approval_id": "3ec064f4-...",
  "status": "approved",
  "run_id": "ef3b5bb3-...",
  "execution_status": "completed",
  "final_response": "Based on the tool output: Successfully wrote 11 characters to hello.txt."
}
```

### 5. Inspect Complete Audit Trace for a Run
```bash
curl -X GET http://localhost:8000/v1/runs/ef3b5bb3-...
```

---

## Technical Details

### Model Routing & `RoutingContext`
All model invocations pass through `ModelRouter.route(ModelRequest)`. Each request carries an explicit, typed `RoutingContext` (`app.models.base.RoutingContext`):
- `task_type`: Optional category or classification of task being routed (`str | None`).
- `complexity`: Problem complexity rating (`"simple" | "medium" | "complex" | None`).
- `privacy_requirement`: Privacy constraint (`"public" | "internal" | "confidential" | None`).
- `latency_preference`: Latency sensitivity (`"low" | "normal" | None`).
- `cost_preference`: Cost budget preference (`"low" | "normal" | "high_quality" | None`).
- `required_capabilities`: List of required tool capabilities (`List[str]`, default `[]`).


### Checkpoint Security (`LANGGRAPH_STRICT_MSGPACK`)
AURA enforces `LANGGRAPH_STRICT_MSGPACK=true` in `app/core/settings.py`. This restricts LangGraph msgpack deserialization strictly to `SAFE_MSGPACK_TYPES`, preventing remote code execution via untrusted callables stored in checkpoint databases.

### Phase 2 Platform Capabilities
1. **Production Long-Term Memory & Vector Persistence:**
   - Multi-tier memory synthesis: Working, Episodic, Semantic, Profile, Project.
   - Dual-engine vector store: `pgvector` (PostgreSQL cosine distance `<=>` with HNSW index) and deterministic in-memory cosine fallback for SQLite testing.
   - Provider-neutral embeddings (`MockEmbeddingProvider`, `OpenAIEmbeddingProvider`, `EmbeddingRouter`).
   - Conservative candidate extraction pipeline with strict fact superseding and audit lineage (`is_active`, `supersedes_id`, `superseded_by_id`).

2. **Model Context Protocol (MCP) Tool Bus:**
   - Official Python MCP SDK v2 (`mcp>=2.0.0`) integration supporting `stdio` and `sse` transports.
   - Dynamic tool discovery via `tools/list` and dispatch via `tools/call`.
   - AURA local security policy overlay: external MCP tools require explicit approval by default; input validation via JSON schema.
   - Server-level crash and fault isolation: external server failures produce structured error results without crashing the orchestrator.

3. **Isolated Docker Execution Sandbox:**
   - Ephemeral container sandbox (`sandbox_shell_execute`, `sandbox_python_execute`).
   - Hardened security defaults: non-root (`user: "1000:1000"`), read-only rootfs (`read_only=True`), network disabled (`network_mode="none"`), memory quota (512MB), CPU quota (1.0 core), PID limit (64), workspace mount only.
   - Governed by human-in-the-loop approval (`RiskLevel.HIGH`).

4. **Event Infrastructure & Persistent Scheduler:**
   - Transactional Event Outbox (`events` table) with structured `AURAEvent` taxonomy (`timer.fired`, `cron.tick`, `webhook.received`).
   - Persistent Scheduler (`scheduled_jobs` table) supporting durable one-shot timers and recurring schedules that survive system restarts.
   - `EventToAgentBridge`: Deterministic triggering bridge connecting scheduled events to Personal Orchestrator runs.

---

## Architecture Decision Records (ADRs)
- [ADR-001: LangGraph Orchestration Runtime](docs/architecture/adr/ADR-001-langgraph-orchestration.md)
- [ADR-002: PostgreSQL + pgvector for Long-Term Memory](docs/architecture/adr/ADR-002-postgresql-pgvector-memory.md)
- [ADR-003: Provider-Neutral Model Interface](docs/architecture/adr/ADR-003-provider-neutral-model-interface.md)
- [ADR-004: Capability-Based Tool Permissions](docs/architecture/adr/ADR-004-capability-tool-permissions.md)
- [ADR-005: Workspace Sandbox Isolation](docs/architecture/adr/ADR-005-isolated-execution-sandbox.md)
- [ADR-006: LangGraph Durable Interruption & Checkpointing](docs/architecture/adr/ADR-006-langgraph-interrupt-checkpointing.md)
- [ADR-007: pgvector Vector Persistence and Embedding Abstraction](docs/architecture/adr/ADR-007-pgvector-and-embedding-abstraction.md)