# ADR-006: LangGraph Durable Interruption and Checkpointing for Human Approvals

## Status
Accepted

## Context
In AURA Phase 1, human-in-the-loop (HITL) tool approvals were initially handled via manual state reconstruction:
1. The graph entered an `approval_pause` node and terminated.
2. An API endpoint (`/v1/approvals/{approval_id}/approve`) manually queried the database, extracted parameters, reconstructed an `AgentState`, and called `execute_tool_node()`, `verify_result_node()`, and `update_memory_node()` sequentially outside the graph engine.

This approach suffered from major architectural deficiencies:
- **No durable graph lifecycle:** The run was not paused in the orchestrator graph; it was abruptly terminated, and resumed via an unmanaged script loop bypassing graph transitions.
- **Lost graph context:** Intermediate state variables, node configs, checkpoint history, and graph listeners were bypassed upon resumption.
- **Process vulnerability:** If the process restarted while waiting for approval, the graph had no persistence layer to safely resume from where it left off.
- **State divergence:** Bypassing graph compilation meant graph edge conditions and future subgraphs could not participate in resumed execution.

## Decision
We refactor the approval lifecycle to use **native LangGraph interruption (`interrupt()`) and durable SQLite checkpointing (`AsyncSqliteSaver`)** with strict per-tool security:

1. **Per-Tool Approval Security (`tool_call_id`):**
   - Approvals are explicitly bound to a specific `tool_call_id`, never solely to `run_id`.
   - In `route_decision_node`, permissions are evaluated independently for every tool call:
     - Safe calls (e.g. read operations) auto-execute without interrupting.
     - Each call requiring approval creates an `ApprovalModel` record with its unique `tool_call_id` and calls `interrupt({"approval_id": ..., "tool_call_id": ..., "tool_name": ..., "tool_input": ..., "risk_level": ...})`.
   - Multi-tool runs handle approvals sequentially via a feedback loop in the orchestrator graph: `determine_next_route` routes back to `route_decision` until all unapproved tool calls have decisions recorded in `state["tool_approvals"]`.
   - In `execute_tool_node`, defense-in-depth ensures unapproved or rejected tool calls are strictly blocked and never executed. Edited approvals apply parameter modifications only to that specific `tool_call_id`.

2. **Durable Persistence (`AsyncSqliteSaver`) and Checkpoint Security:**
   - The orchestrator graph is compiled with `AsyncSqliteSaver` (backed by `aura_checkpoints.db`) during application startup.
   - For unit testing environments, an in-memory `MemorySaver` can be swapped via `set_global_checkpointer()`.
   - Thread ID semantics are strictly bound: `{"configurable": {"thread_id": run_id}}`.
   - **Checkpoint Security:** Strict MessagePack serialization is enforced via `LANGGRAPH_STRICT_MSGPACK=true` to prevent insecure arbitrary Python object deserialization in SQLite checkpoints.

3. **Resumption via `Command(resume=...)` & Crash-Safe Reconciliation:**
   - Human decisions are submitted via `/v1/approvals/{approval_id}/decision` (or legacy `/approve`, `/reject`, `/edit` aliases).
   - The endpoint queries `graph.aget_state(config)` to inspect `snapshot.next`:
     - If the graph is paused at an interrupt, the decision is recorded and `Command(resume=...)` resumes execution.
     - **Crash Recovery & Idempotency:** If the process previously committed the decision to DB and crashed before graph resume completed, or if a client retries an already-processed approval, the endpoint detects that `snapshot.next` is empty and returns the final run state idempotently without raising 400.
     - **Error Handling:** If an LLM provider fails during resume execution, the run is safely marked `RunStatus.FAILED` with a `run_failed` audit event.

4. **Idempotency and Re-execution Safety:**
   - Resuming an interrupted node in LangGraph re-enters the node function until `interrupt()` returns the payload.
   - To prevent duplicate approval requests or traces, `route_decision_node` queries `approval_service.get_approval_by_tool_call(tool_call_id)` before creating new approval records.

## Consequences

### Positive
- **True pause & resume:** The entire orchestrator graph maintains genuine paused execution semantics.
- **Per-tool authorization granularity:** Approving one tool call can never inadvertently authorize another unapproved tool call in multi-tool runs.
- **Crash resilience:** If the server is restarted or crashes while a run is waiting for approval or during resume, the state is preserved and safely recoverable.
- **Secure deserialization:** Checkpoints avoid pickle vulnerabilities via strict MessagePack enforcement.
- **Trace completeness:** Graph audit traces capture the exact lifecycle: `approval_requested` -> `approval_granted` -> `tool_executed` -> `run_completed`.

### Negative / Trade-offs
- Checkpoint database management: requires managing checkpoint database connections during FastAPI startup and shutdown lifespans (`init_checkpointer()` and `close_checkpointer()`).
- Re-execution care: node logic preceding `interrupt()` must be strictly idempotent to avoid duplicate side effects upon resumption.
