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
User-created projects can be archived and restored. Archiving hides them from
default project navigation while retaining their project record, conversations,
files, notes, routing assignment, and history; it does not delete data or stop
scheduled automations.

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
| LangGraph execution checkpoints | `AsyncSqliteSaver` at `CHECKPOINT_DB_PATH`, separate from the SQLAlchemy database. Docker Compose stores it in the persistent `checkpoint_data` volume. |
| Board layout | Project workspace layout with revision checks; layout is user state rather than graph knowledge. |
| User-created projects | Workspace project directory in the SQLAlchemy database; built-in sample projects remain clearly client-side demo data. |
| Connected folder handles and search index | Browser IndexedDB; the user explicitly indexes a connected folder, storing file names and metadata only. File contents remain at the original path and are read only when the user opens a file. From the File tab, the user may explicitly copy an opened file into the browser-local Library for later Send text context; the original stays in place. |
| Provider inventory | In-memory capability registry populated by native tool registration and MCP discovery. |

Strict LangGraph MessagePack deserialization is enabled by
`LANGGRAPH_STRICT_MSGPACK`. A database backup does not replace a checkpoint
backup; deployments that need durable recovery must preserve both configured
stores. Compose deployments must retain both `postgres_data` and
`checkpoint_data` across container recreation.

Outbox workers renew processing leases while handlers run and reclaim leases
left by crashed workers. Proactive event runs use deterministic run IDs; a
retry resumes a persisted LangGraph checkpoint, or starts the run if the
process stopped before the first checkpoint. Completed and approval-paused
runs are not invoked again by duplicate event delivery. Manual, webhook, and
retry triggers acquire a shared atomic short lease before enqueueing, so
single-run admission also holds with the local SQLite database where row-level
`FOR UPDATE` locks are not available.

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

Live research search combines Semantic Scholar and arXiv, then uses Crossref as
a final metadata-only fallback when fewer than the requested number of sources
were returned. Live search queries are sent to these providers unless the run
is classified `confidential` or `local_only`, in which case AURA blocks
external provider search before sending the query. The deterministic corpus
remains available within those privacy boundaries. Crossref results include
bibliographic metadata only; AURA does not request Crossref abstracts or full
text. A failure from one provider does not discard sources returned by the
others. When no provider completes the search, the tool reports a structured
provider error instead of claiming that the query returned no matches; a
successful search with zero matches remains a normal empty result.

## Capability and execution boundaries

Specialists request abstract capabilities. The capability registry maps those
requests to canonical AURA tool names only when a provider explicitly declares
the mapping. Required capabilities fail closed. Optional capabilities are
added only when an enabled provider currently supplies matching tools and do
not block the specialist when unavailable.
Pending approval reads use stable bounded pages (10 by default, 25 maximum)
because approval records can carry sizeable tool inputs.

MCP configuration is loaded from `MCP_CONFIG_PATH`. AURA discovers tools,
applies its local MCP risk policy, validates arguments against the advertised
JSON schema, and then dispatches calls through the configured server. Provider
metadata is descriptive; AURA's scoped tool registry, permission policy, and
approval service govern invocation. External code graph providers remain
optional and user-installed; see the [provider guide](../capabilities/code-graph-providers.md).

Coding shell and Python execution use the sandbox runtime. Its default Docker
profile uses a non-root user, read-only root filesystem, disabled network,
resource limits, and an approval-gated high-risk tool policy. Workspace file
tools remain confined to `AURA_WORKSPACE_ROOT`. New workspace roots use
owner-only POSIX permissions; Docker execution matches the workspace owner
where possible and does not broaden permissions on an existing directory.

## Workspace graph and context

Workspace objects and edges provide a shared substrate for conversation turns,
manual notes, context bridges, context sets, branches, and operational
provenance. Semantic relationships may cycle; context-flow edges are validated
to remain acyclic. Board layout is stored separately from object relationships.
Project, personal note, Library, Study, and Automation collection reads use
bounded keyset pages; the API returns arrays with an `X-Next-Cursor` response
header. Composite indexes match the filters and cursor ordering for workspace
graphs and collections, session messages, memories, pending approvals, routing
confirmations, run traces, project execution history, automation listings, and
automation history. Notes, Library references, and automations load older pages
on demand; aggregate counts come from lightweight summary endpoints instead of
the pages currently held in the browser. Automation run history is also
cursor-paged, with older runs loaded on demand.
Library search runs against persisted reference metadata and keeps the same
cursor pagination, so matches are not limited to the references already loaded
in the browser. It searches names, collection, detail, and tags; local file
contents remain outside the index. Project Files applies the same search within
references linked to the current project and keeps paging within that scope.
The top-bar Search overlay queries persisted workspace objects and, at personal
scope, browser-local connected-folder indexes. Folder matches expose indexed
names and paths only; opening one reads the file after the user's explicit
action. It shows returned excerpts and opens the selected saved object. It does
not generate an AI answer or invent source cards; model-backed question
answering remains in a live chat.
Saved automations can update their name, description, instruction, and interval
without changing project scope or the stable session used for their history.
Already queued events keep their original instruction payload; the next
scheduled event uses the updated settings.
Automations can be archived to stop future schedules while preserving run
history; restore returns them as paused routines.
Saved automations can also be duplicated into a paused routine with its own
session and run history, so copying a schedule never copies execution history
or starts a second schedule unexpectedly.
Queued Automation runs can be cancelled only while their outbox event remains
pending and unclaimed. Once a worker claims a run, cancellation is rejected; the
interface does not claim to stop an active tool or model execution.
Automations may also accept bearer-authenticated webhook signals. A newly enabled trigger
returns a random bearer secret once and stores only its SHA-256 digest. Send
`Authorization: Bearer <secret>` and a unique `X-Aura-Event-Id`; duplicate
deliveries return the original queued event. The request body is deliberately
ignored and never enters the run prompt or event record. Webhook signals use
the same durable outbox, approval flow, and local-only routing policy as other
Automation runs. Paused or archived automations reject new webhook runs.
Automation run summaries preserve whether each event came from a schedule, a
manual run, a webhook, or a retry. Failed and dead-lettered executions can be
retried as a fresh event using the Automation's current saved instruction; the
new history record links back to the prior event, and webhook request bodies
are never replayed. See the [webhook setup and delivery contract](../automations-webhooks.md).

The Library's Research collection includes a read-only Research Radar for saved
project graphs. It requests bounded graph pages filtered to research sources,
evidence, claims, and provenance edges, so unrelated conversation objects do
not consume its pages. It does not infer new
relationships or modify research artifacts. Each artifact can open at its saved
object in the project Board. Verified claims can start a Study session through
the existing Study API; qualified or unsupported claims cannot. Study history
keeps a link back to the source claim's project Board. Learning cards persist
their review count and next review date with the workspace object. A review
rating schedules the next review after 1, 3, or 7 days; changing a card's
question or answer resets that schedule. Study's keyset-paged review queue
shows unreviewed cards and cards whose next review date has arrived.

Chat requests may select project-scoped workspace object IDs. The Context
Compiler validates scope, follows only explicitly selected/linked context
objects, applies object and character limits, and records a provenance
manifest with the run. Context Bridges compile their user-authored handoff note
and only the structured sections the user enabled. Source links retain
provenance and strengthen privacy routing without copying full source content
into the handoff. Context Sets and branches expand their explicitly linked
sources. The root prompt labels assembled material as retrieved AURA context
and directs the model to use content already present there; tools remain for
missing information, current-state checks, and requested actions.

Imported browser-local TXT, Markdown, CSV, JSON, and HTML files remain in the
browser unless a live-chat user explicitly selects **Send text**. Plain text
files decode UTF-8 by default and honor UTF-8, UTF-16LE, and UTF-16BE BOMs.
Plain text input is limited to 80,000 bytes and 20,000 decoded characters.
Imported RTF files are reduced to plain text locally, including paragraph,
Unicode, and Windows-1252 escaped text. Formatting and embedded object data are
omitted; the parser accepts up to 80,000 bytes and returns at most 20,000
characters. The original RTF remains browser-local until the user explicitly
selects **Send text**.
Imported PDFs can also be parsed locally after that explicit action; selectable
text is read directly and textless pages use bundled English/Vietnamese OCR
models, capped at five pages per file. The browser parser enforces a 10 MB file
limit, a 100-page limit, and the existing 20,000-character per-file limit.
Imported DOCX files can be parsed locally in the browser under a 10 MB input and
20,000-character extracted-text limit.
Imported HTML files are parsed locally into body text after that explicit
action, with script, style, hidden, and embedded content removed; input is
limited to 80,000 bytes and extracted text to 20,000 characters. HTML previews
run in a sandboxed frame without script or same-origin permissions.
Imported XLSX workbooks can also be parsed locally after that explicit action;
only visible worksheets are included, with limits of 10 sheets, 250 rows per
sheet, 40 columns per row, and 20,000 extracted characters.
Imported PPTX presentations can also be parsed locally after that explicit
action. Only slide text is included; macro-enabled and legacy presentations
remain reference-only. The ZIP reader streams slide XML with a 10 MB input,
100-slide, 1 MB per-slide XML, 20 MB aggregate expansion, and 20,000-character
text limit.
Imported EPUB e-books can also be parsed locally after that explicit action.
Only text chapters in the EPUB spine are included, in reading order. Scripts,
styles, embedded content, and resource URLs are removed before parsing so local
extraction does not load remote chapter resources; input is limited to 10 MB,
100 chapters, 1 MB per chapter, 20 MB aggregate expansion, and 20,000 extracted
characters.
Imported raster images can be OCRed locally after that explicit action. The
browser sends extracted text only, never the image pixels for vision; input is
limited to 10 MB and 20 megapixels, downscaled locally, and capped at 20,000
characters.
Legacy DOC and other unsupported binary formats remain reference-only. Sending
any extracted text copies bounded content into the durable run checkpoint for
resume and requires cloud confirmation without changing the profile's fallback policy; the normal
routing-confirmation workflow must be resolved before a cloud model can receive
it. The Library graph retains only the file reference and provenance manifest,
not the file text.

Compiled object metadata can add model requirements (`vision`,
`structured_output`, and `long_context`) and abstract tool capabilities to the
turn's `RoutingContext`. Tool capabilities must resolve through an enabled
provider registration or compilation fails closed. The context preview uses
the same compiler and reports the normalized routing flags without invoking a
model or writing workspace data. Live chat also measures the assembled prompt
and tool definitions before selecting a model. Neither the compiler manifest
nor the Execution Graph exposes hidden chain-of-thought or raw context text in
telemetry.

Embedding requests carry the effective privacy requirement too. Only providers
declaring a local or air-gapped boundary may embed confidential or local-only
content. If the configured provider cannot meet that boundary, AURA skips
semantic lookup or retains the memory without a vector; it does not silently
send the text to a cloud embedding service or substitute another provider.
Correcting an active project memory creates a superseding version with the same
project/key/privacy metadata and preserves the old record and provenance. The
replacement vector is regenerated only when the configured embedder satisfies
that memory's privacy requirement.

The Execution Graph is a read-only projection of persisted run events. Run-event
records and their structured logs keep operational metadata while excluding
prompts, tool arguments, raw outputs, and hidden reasoning. Chat messages and
final responses remain in their dedicated session/run records so conversation
history can be restored; they are not copied into telemetry events.

## Frontend and verification

The frontend is React + TypeScript + Vite under `web/`. The dev server runs on
port 5173 and proxies `/v1` to the API on port 8000. Persistent Board, chat,
routing, context compilation, and execution views use the API; local/demo data
is marked separately from live backend conversations.

GitHub Actions is the release gate for the integrated backend, Phase 1, Phase
2.1, Phase 3, Phase 4, frontend tests, and production build.

`GET /health` is a process liveness probe. `GET /ready` checks the configured
database connection and performs a read-only lookup through the LangGraph
checkpointer; it returns HTTP 503 when either dependency needed for durable
runs is unavailable.
