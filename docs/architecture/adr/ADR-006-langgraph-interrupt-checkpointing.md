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
We refactor the approval lifecycle to use **native LangGraph interruption (`interrupt()`) and durable SQLite checkpointing (`AsyncSqliteSaver`)**:

1. **Native Interruption:**
   - In `route_decision_node`, when a tool execution requires human authorization according to `PermissionPolicy`, the node calls `interrupt({"approval_id": ..., "tool_name": ..., "tool_input": ..., "risk_level": ...})`.
   - Execution suspends cleanly at this exact node. LangGraph serializes the complete `AgentState` into the configured checkpointer.

2. **Durable Persistence (`AsyncSqliteSaver`):**
   - The orchestrator graph is compiled with `AsyncSqliteSaver` (backed by `aura_checkpoints.db`) during application startup.
   - For unit testing environments, an in-memory `MemorySaver` can be swapped via `set_global_checkpointer()`.
   - Thread ID semantics are strictly bound: `{"configurable": {"thread_id": run_id}}`.

3. **Resumption via `Command(resume=...)`:**
   - When a human approves, rejects, or edits a tool request via `/v1/approvals/{approval_id}/approve` (or reject/edit), the API issues:
     ```python
     command = Command(resume={"decision": "approved", "decision_notes": ...})
     await graph.ainvoke(command, config={"configurable": {"thread_id": run_id}})
     ```
   - Execution resumes exactly inside `route_decision_node` with the resume payload returned from `interrupt()`.
   - If approved, execution proceeds along the graph edge to `execute_tool_node` -> `verify_result_node` -> `update_memory_node` -> `END`.
   - If rejected, execution transitions cleanly to `cancelled` and terminates.

4. **Idempotency and Re-execution Safety:**
   - Resuming an interrupted node in LangGraph re-enters the node function until `interrupt()` returns the payload.
   - To prevent duplicate approval requests or traces, `route_decision_node` queries `approval_service.get_approval_by_run(run_id)` before creating new approval records.

## Consequences

### Positive
- **True pause & resume:** The entire orchestrator graph maintains genuine paused execution semantics.
- **Process survival:** If the server is restarted while a run is `waiting_for_approval`, the run state is fully preserved in SQLite and can be resumed at any time by thread ID.
- **Graph integrity:** Resumed runs execute within the compiled graph, honoring all graph edges, interceptors, and reducers.
- **Trace completeness:** Graph audit traces capture the exact lifecycle: `approval_requested` -> `approval_granted` -> `tool_executed` -> `run_completed`.

### Negative / Trade-offs
- Checkpoint database management: requires managing checkpoint database connections during FastAPI startup and shutdown lifespans (`init_checkpointer()` and `close_checkpointer()`).
- Re-execution care: node logic preceding `interrupt()` must be strictly idempotent to avoid duplicate side effects upon resumption.
