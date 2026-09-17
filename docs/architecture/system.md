# AURA System Architecture Specification

## Document Overview
- **Project Codename:** AURA (Adaptive User Runtime Agent)
- **Status:** Approved / Active
- **Version:** 1.0.0 (Phase 0 & 1 Baseline)
- **Author:** Lead Systems Architect & Implementation Engineer

---

## 1. System Overview & Boundaries

AURA is a production-grade personal AI agent runtime designed for persistence, security, predictability, and extensibility. Unlike basic chatbots that merely stream completions over an unbounded chat history, AURA treats the agent as a long-running, stateful operating process with discrete memory subsystems, sandboxed execution boundaries, capability-based permission checks, and explicit human-in-the-loop approvals.

```mermaid
flowchart TB
    subgraph External["External World (Untrusted)"]
        User["User / UI Clients"]
        ExtAPI["External APIs & Services"]
        HostOS["Host OS Filesystem"]
    end

    subgraph BoundaryGateway["Security Gateway & API Boundary"]
        APIGateway["FastAPI Gateway (/v1)"]
    end

    subgraph CoreRuntime["AURA Trusted Runtime"]
        Orchestrator["Personal Orchestrator (LangGraph)"]
        MemorySubsystem["Memory Service (Working, Episodic, Semantic, Profile, Project)"]
        ModelRouter["Model Router Abstraction"]
        CapabilityEngine["Capability & Permission Policy Engine"]
        ApprovalLayer["Human-in-the-Loop Approval Service"]
        TraceEngine["Observability & Tracing Engine"]
    end

    subgraph SandboxBoundary["Execution Sandbox Boundary"]
        ToolRuntime["Tool Runtime Engine"]
        WorkspaceSandbox["Workspace Isolated Sandbox"]
    end

    subgraph StorageBoundary["Persistence Layer"]
        PostgresDB[("PostgreSQL 16 + pgvector")]
    end

    User <-->|HTTP REST / JSON| APIGateway
    APIGateway <--> Orchestrator
    Orchestrator <--> MemorySubsystem
    Orchestrator <--> ModelRouter
    Orchestrator <--> CapabilityEngine
    CapabilityEngine <--> ApprovalLayer
    Orchestrator <--> ToolRuntime
    ToolRuntime <--> WorkspaceSandbox
    WorkspaceSandbox -.->|Scoped Access Only| HostOS
    MemorySubsystem <--> PostgresDB
    TraceEngine <--> PostgresDB
    ApprovalLayer <--> PostgresDB
    ModelRouter <--> ExtAPI
```

### System Boundaries
1. **API Boundary:** External clients communicate strictly via typed REST APIs (`/v1/chat`, `/v1/approvals`, `/v1/sessions`, `/v1/runs`). No internal agent state dictionaries or memory handles are directly exposed.
2. **Model Boundary:** The orchestrator never calls vendor SDKs directly. All requests pass through a provider-neutral `ModelRouter`.
3. **Tool & Sandbox Boundary:** Tools execute within a confined sandbox. Tools interacting with the host filesystem are restricted to a strictly configured workspace directory. Any path traversal outside the workspace is denied.
4. **Approval Boundary:** Destructive or state-mutating actions (such as filesystem modifications or shell execution) require explicit approval before execution. Execution halts until an approval decision is recorded.
5. **Persistence Boundary:** All state (sessions, messages, runs, traces, approvals, and episodic memories) is persisted to relational storage (PostgreSQL). State is never solely retained in volatile process memory.

---

## 2. Major Components

| Component | Module Path | Responsibility |
| :--- | :--- | :--- |
| **API Gateway** | `app.api` | Request validation, authentication, route dispatching, response serialisation. |
| **Personal Orchestrator** | `app.orchestrator` | LangGraph-based state machine managing the agent reasoning, tool dispatch, approval pause/resume, and lifecycle. |
| **Model Router** | `app.models` | Provider-neutral model execution, fallback handling, provider abstraction (OpenAI, Gemini, Local, Mock). |
| **Memory Subsystem** | `app.memory` | Multi-tier memory architecture (Working, Episodic, Semantic, Profile, Project). |
| **Tool Runtime** | `app.tools` | Registry and execution harness for declared tools with metadata, schema validation, and capability requirements. |
| **Capability & Approval** | `app.approvals` | Capability taxonomy, permission policy enforcement, pending approval management. |
| **Sandbox Environment** | `app.sandbox` | Isolation boundary enforcing workspace jail and future containerised execution. |
| **Observability & Tracing**| `app.observability` | Structured event logging, persistent audit trails (`run_events`), run reconstruction. |
| **Database & Persistence**| `app.db` | SQLAlchemy 2.x models, async session management, Alembic migrations. |

---

## 3. Data Flow & Execution Lifecycle

The lifecycle of an interaction through `POST /v1/chat`:

```mermaid
sequenceDiagram
    autonumber
    actor Client as User / Client
    participant API as FastAPI Gateway
    participant Orch as LangGraph Orchestrator
    participant Mem as Memory Service
    participant Router as Model Router
    participant Policy as Permission Policy
    participant Appr as Approval Service
    participant Tool as Tool Runtime & Sandbox
    participant Trace as Observability Tracer

    Client->>API: POST /v1/chat {session_id, message}
    API->>Trace: Emit 'request_received'
    API->>Mem: Load session & recent context (Working Memory)
    API->>Orch: Invoke Orchestrator(state)
    
    Orch->>Trace: Emit 'context_loaded'
    Orch->>Router: Reason & Generate Plan / Tool Request
    Router-->>Orch: ModelResponse (Direct Answer or ToolCall)

    alt Direct Response
        Orch->>Trace: Emit 'response_generated'
        Orch->>Mem: Update Memory (Working & Episodic)
        Orch-->>API: Final AgentState
        API-->>Client: 200 OK {response, run_id, status: "completed"}
    else Tool Call Required
        Orch->>Trace: Emit 'tool_requested'
        Orch->>Policy: Evaluate Tool Required Capabilities
        
        alt Automatic Permission (e.g., filesystem.read)
            Policy-->>Orch: Allowed
            Orch->>Tool: Execute Tool in Sandbox
            Tool-->>Orch: ToolResult
            Orch->>Trace: Emit 'tool_executed'
            Orch->>Router: Reason with Tool Result
            Router-->>Orch: ModelResponse (Final Answer)
            Orch->>Mem: Update Memory
            Orch-->>API: Final AgentState
            API-->>Client: 200 OK {response, run_id, status: "completed"}
        else Requires Approval (e.g., filesystem.write)
            Policy-->>Orch: Approval Required
            Orch->>Appr: Create Pending Approval Record
            Orch->>Trace: Emit 'approval_requested'
            Orch-->>API: State Paused (execution_status: "waiting_for_approval")
            API-->>Client: 200 OK {status: "waiting_for_approval", approval_id, run_id}
            
            Note over Client,Appr: Out-of-band user decision
            Client->>API: POST /v1/approvals/{id}/decision {decision: "approved"}
            API->>Appr: Record Decision
            API->>Orch: Resume Run (run_id, approval_id)
            Orch->>Tool: Execute Approved Tool in Sandbox
            Tool-->>Orch: ToolResult
            Orch->>Router: Generate Final Response
            Orch->>Mem: Update Memory
            Orch-->>API: Completed AgentState
            API-->>Client: 200 OK {response, status: "completed"}
        end
    end
```

---

## 4. Agent State Model (`AgentState`)

Agent state in AURA is explicitly typed, immutable per step, and serialized cleanly across transitions:

```python
class AgentState(TypedDict):
    run_id: str                      # Unique UUID for the current execution run
    session_id: str                  # Session UUID representing conversation thread
    user_message: str                # Current user input message
    messages: list[dict[str, Any]]   # Standardized message history (role, content, etc.)
    retrieved_context: list[str]     # Injected memory context items
    current_plan: str | None         # High-level plan or reasoning scratchpad
    tool_requests: list[dict]        # Pending or active tool calls from model
    tool_results: list[dict]         # Executed tool results
    approval_id: str | None          # Associated approval ID if paused
    approval_state: str              # "none" | "pending" | "approved" | "rejected" | "edited"
    execution_status: str            # "running" | "waiting_for_approval" | "completed" | "failed"
    errors: list[str]                # Trace of non-fatal and fatal errors
    final_response: str | None       # Final markdown answer intended for the user
```

---

## 5. Trust & Security Boundaries

### 5.1 Trust Model
- **Untrusted:** Raw user inputs, external network payloads, and unverified model outputs (which may hallucinate commands or attempt jailbreaks).
- **Semi-Trusted:** The LLM reasoning outputs (treated as untrusted proposals until verified by the permission and sandbox layers).
- **Trusted:** The core orchestrator, memory service, capability engine, and approval service running inside the AURA host environment.

### 5.2 Model-Provider Boundary
- Orchestrator components interact exclusively with `ModelRouter`.
- `ModelRouter` accepts typed `ModelRequest` and returns typed `ModelResponse`.
- Provider implementations (`OpenAIProvider`, `MockProvider`, etc.) adapt vendor APIs to AURA internal domain schemas.
- Provider secrets are read strictly from application settings; they are never passed through conversation state or logged.

### 5.3 Memory Boundary
Memory is partitioned into five distinct cognitive tiers:
1. **Working Memory:** Current turn execution state and active session conversation buffer.
2. **Episodic Memory:** Chronological narrative records of significant past runs, decisions, and tool executions.
3. **Semantic Memory:** Extracted declarative facts, indexed with vector embeddings (`pgvector`) for cosine similarity retrieval.
4. **Profile Memory:** Key-value store of persistent user preferences, system constraints, and identity details.
5. **Project Memory:** Contextual facts, workspace paths, and domain knowledge scoped to a specific project.

### 5.4 Tool & Capability Boundary
- Every tool declares explicit required capabilities (`filesystem.read`, `filesystem.write`, `shell.execute`, `network.access`).
- Tools never perform self-authorization. Authorization is strictly performed by `PermissionPolicy`.
- Path traversal protection: All filesystem tools must resolve candidate paths against `AURA_WORKSPACE_ROOT` using strict canonical path resolution (`Path.resolve()`). If the resolved path does not start with the workspace root, access is denied immediately.

### 5.5 Sandbox Boundary
- In Phase 1, the sandbox boundary is enforced at the filesystem level: directory jailing to `AURA_WORKSPACE_ROOT`.
- In Phase 2, shell and code execution tools will run exclusively inside ephemeral container sandboxes (e.g., rootless Docker or gVisor) with network egress isolation and strict resource quotas.

### 5.6 Approval Boundary
- The approval layer enforces Human-in-the-loop control.
- Any action flagged with risk level `HIGH` or `CRITICAL`, or requiring capabilities categorized as `requires_approval` (such as `filesystem.write`), stops graph execution.
- The approval object records: `approval_id`, `run_id`, `session_id`, `tool_name`, `tool_input`, `risk_level`, `status`, and timestamps.
- Execution cannot resume until a valid decision (`approved`, `rejected`, or `edited`) is committed to the database.

---

## 6. Future Event-Driven Architecture

In future phases, AURA will support autonomous and proactive operations triggered by external events:
- **Event Ingestion:** Webhook receivers, file system watchers, and cron schedulers publish events to an internal event bus.
- **Event Normalization:** Raw events are transformed into standard `AgentEvent` objects.
- **Proactive Run Dispatch:** An Event Dispatcher identifies matching triggers, retrieves associated profile/project memory, and creates a background execution run with the Personal Orchestrator.

---

## 7. Future Specialist Agent Architecture

Specialist agents will be integrated as specialized sub-graphs or worker nodes under the Personal Orchestrator:
- **Root Controller:** The Personal Orchestrator remains the root controller, retaining memory ownership, user relationship, and approval governance.
- **Specialists:** Research Agent, Coding Agent, Computer Agent, and Writing Agent will be invoked with scoped sub-tasks, returning structured artifacts to the orchestrator for verification before memory commit.

---

## 8. Summary of Architectural Principles

1. **Explicit over implicit:** State and decisions are clear, typed, and auditable.
2. **Fail-safe defaults:** Unrecognized capabilities default to denial. File writes default to requiring approval.
3. **Zero-secret leakage:** API keys and credentials never enter logging or message history.
4. **Resilience:** Restarts do not lose session history, runs, or pending approvals.
