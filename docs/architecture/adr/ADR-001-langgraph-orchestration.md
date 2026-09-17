# ADR-001: LangGraph as Orchestration Runtime

## Status
Accepted

## Context
AURA requires a stateful, predictable, observable agent orchestration runtime capable of:
1. Managing complex workflows with conditional routing (direct response vs tool execution vs human approval).
2. Pausing execution cleanly when human approval is required and resuming without loss of state.
3. Providing inspectable, deterministic state transitions rather than opaque autonomous loops.
4. Supporting future expansion to multi-agent specialist subgraphs.

Traditional agent loops (such as ReAct loops with raw while-loops or unstructured LangChain chains) suffer from unpredictable recursion, state mutations hidden in closures, difficult persistence, and fragile breakpoint handling.

## Decision
We select **LangGraph** (`langgraph`) as the core orchestration runtime for AURA.

Specifically:
- We model the agent as a compiled `StateGraph` over an explicit typed `AgentState`.
- Orchestrator steps are discrete pure or state-transforming nodes (`load_context`, `reason`, `route`, `execute_tool`, `approval_pause`, `verify_result`, `update_memory`).
- Routing decisions are explicit conditional edges based on state attributes (`tool_requests`, `approval_state`, `execution_status`).
- Approvals leverage explicit graph checkpoints and state persistence: when an action requires approval, the graph transitions to an approval wait state and terminates the turn, allowing out-of-band resumption once a decision is recorded.

## Consequences
### Positive
- **Deterministic state machine:** State transitions are typed and inspectable at every node.
- **Resilient persistence:** Checkpoints can be committed to database storage, enabling session survival across application restarts.
- **Native human-in-the-loop:** LangGraph's architecture naturally accommodates pausing for human approval.
- **Future-proof:** Subgraphs for specialist agents can be seamlessly attached without breaking top-level orchestrator contracts.

### Negative / Trade-offs
- Requires defining explicit schemas and transitions for every step rather than relying on rapid prototyping black-box agent loops.
- Requires careful handling of async state updates and database transactions across nodes.
