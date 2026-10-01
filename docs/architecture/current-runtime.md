# AURA Current Runtime Architecture

This document describes the implementation in the current repository. The
[Phase 0/1 system specification](system.md) remains useful as a historical
baseline, but it is not a complete description of the current product.

## Product shape

AURA is a personal workspace with a root orchestrator, durable runs, memory,
model routing, capability-scoped tools, and approval-gated execution. The web
workspace has permanent Home, Library, Notes, Study, Automations, and Projects
surfaces. A project is one reusable tab with Overview, Chat, Board, Split, and
Files views. Chat and Board are views over shared project conversation objects.

## Request and execution path

```text
React/Vite workspace
    → FastAPI /v1 API
    → session/project and routing resolution
    → LangGraph root orchestrator
    → context loading and compilation
    → provider-neutral model router
    → scoped AURA tools or a controlled specialist child run
    → capability permission and approval checks
    → execution, trace events, and persisted workspace objects
```

The API creates or loads the session, attaches an explicitly named project,
resolves the routing profile and scope, persists a run snapshot, and invokes
the graph. Specialist runtimes run as children of the root run; they do not
form a peer-agent swarm. The Coding Specialist and Research Specialist receive
separate capability scopes, and specialists cannot recursively delegate.

## Persistence boundaries

| State | Implementation |
| --- | --- |
| Sessions, messages, runs, approvals, routing profiles, traces, and workspace graph | SQLAlchemy database selected by `DATABASE_URL`; SQLite is the local default and Docker Compose uses PostgreSQL with pgvector. |
| LangGraph execution checkpoints | `AsyncSqliteSaver` at `CHECKPOINT_DB_PATH`, separate from the SQLAlchemy database. |
| Board layout | Project workspace layout with revision checks; layout is user state rather than graph knowledge. |
| User-created projects | Workspace project directory in the SQLAlchemy database; built-in sample projects remain clearly client-side demo data. |
| Provider inventory | In-memory capability registry populated by native tool registration and MCP discovery. |

Strict LangGraph MessagePack deserialization is enabled by
`LANGGRAPH_STRICT_MSGPACK`. A database backup does not replace a checkpoint
backup; deployments that need durable recovery must preserve both configured
stores.

## Routing and model calls

Routing profiles can be assigned at system/default, project, or session scope;
message-level and temporary thread overrides are resolved by the routing
layer. The resolved profile, version, scope, privacy, fallback, selected model,
and reasoning decision are persisted with runs and routing events. A model
request receives the tool definitions available to its current runtime scope,
and model selection filters on tool support when those definitions are present.

The model router is provider-neutral. Provider metadata distinguishes
supported, unsupported, and unknown capabilities; it does not infer a model's
identity or feature support from its name. `MODEL_PROVIDER=mock` is the local
default. The Research Specialist uses deterministic sources by default unless
`RESEARCH_PROVIDER_MODE` is explicitly changed.

## Capability and execution boundaries

Specialists request abstract capabilities. The capability registry maps those
requests to canonical AURA tool names only when a provider explicitly declares
the mapping. Required capabilities fail closed. Optional capabilities are
added only when an enabled provider currently supplies matching tools and do
not block the specialist when unavailable.

MCP configuration is loaded from `MCP_CONFIG_PATH`. AURA discovers tools,
applies its local MCP risk policy, validates arguments against the advertised
JSON schema, and then dispatches calls through the configured server. Provider
metadata is descriptive; AURA's scoped tool registry, permission policy, and
approval service govern invocation. External code graph providers remain
optional and user-installed; see the [provider guide](../capabilities/code-graph-providers.md).

Coding shell and Python execution use the sandbox runtime. Its default Docker
profile uses a non-root user, read-only root filesystem, disabled network,
resource limits, and an approval-gated high-risk tool policy. Workspace file
tools remain confined to `AURA_WORKSPACE_ROOT`.

## Workspace graph and context

Workspace objects and edges provide a shared substrate for conversation turns,
manual notes, context bridges, context sets, branches, and operational
provenance. Semantic relationships may cycle; context-flow edges are validated
to remain acyclic. Board layout is stored separately from object relationships.

Chat requests may select project-scoped workspace object IDs. The Context
Compiler validates scope, follows only explicitly selected/linked context
objects, applies object and character limits, and records a provenance
manifest with the run. It does not expose hidden chain-of-thought or copy full
source content into telemetry.

The Execution Graph is a read-only projection of persisted run events. It may
show routing, delegation, tool, and result metadata while excluding prompts,
tool arguments, raw outputs, and hidden reasoning.

## Frontend and verification

The frontend is React + TypeScript + Vite under `web/`. The dev server runs on
port 5173 and proxies `/v1` to the API on port 8000. Persistent Board, chat,
routing, context compilation, and execution views use the API; local/demo data
is marked separately from live backend conversations.

GitHub Actions is the release gate for the integrated backend, Phase 1, Phase
2.1, Phase 3, Phase 4, frontend tests, and production build.
