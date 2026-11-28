# Context Engineering

## Status

Implemented in the post-v1 Context Engineering milestone. The implementation
extends the existing memory and workspace compilers; it does not replace them.
Run manifests are persisted as sanitized `context_package_compiled` events and
shown in the existing Inspector Context tab.

## Runtime flow

```text
Data sources
  → canonical memory/workspace state
  → ContextItem normalization
  → retrieval and hard filtering
  → deterministic ranking and selection
  → model-aware token allocation
  → local context transformation
  → context assembly
  → final prompt-window validation
  → sanitized ContextManifest persistence
  → the already-selected model invocation
```

`ContextAssembler` remains responsible for memory retrieval, and
`WorkspaceContextCompiler` remains responsible for resolving selected objects,
project links, graph ancestry, privacy, and capabilities. Their results become
runtime `ContextItem` candidates in `app/memory/context_engineering.py`.
Explicit browser file text is held once in the durable run's attachment state;
the candidate stores a `content_reference` and resolves that reference only
when the model call is prepared. Candidate content is checkpointed when it
comes from memory or compiled workspace objects so a paused run can resume
without re-fetching a different source version.

The current user request and system policy remain mandatory model messages.
The router is called once. Before that call, Kuractus accounts for those mandatory
messages and explicitly selected/required workspace context so the router can
reject a model that cannot fit it. After routing, the allocator uses the
selected model's actual context-window metadata for optional candidates. The
final serialized prompt and tools are measured again before invocation; if the
window still does not fit, the run fails with a structured context error.

## Candidate priority and scoring

Priority classes are applied before relevance scores:

1. Explicitly selected objects
2. User-authored notes
3. Context Bridges
4. Required conversation ancestry
5. Verified research evidence
6. Project/profile/semantic memory
7. External retrieved context
8. Optional execution history

Current request and system policy are outside this candidate list because they
are mandatory messages. Within a priority class, the deterministic score is:

```text
0.40 × relevance + 0.15 × freshness + 0.25 × authority + 0.20 × utility
```

Known signals are bounded to `[0, 1]`; missing signals use a neutral `0.5` in
the total but remain `null` in the score breakdown. Freshness uses an explicit
`updated_at` timestamp and a 30-day half-life. Graph-linked candidates receive
the fixed relevance signal `0.75` only when the existing compiler provides
source-object links. No authority or freshness is inferred from names or
content. Stable ties use item ID and source ID.

## Hard filters and allocation

Scope, privacy, available capabilities, source provenance shape, supported
type, and expiration are checked before ranking. Only `global` and `project`
scopes are accepted; a project item must name the active project, while a
global item cannot carry a project ID. Missing or contradictory scope metadata
fails closed. A hard-filtered selected or
required item raises `mandatory_context_rejected`; a selected item that cannot
fit raises `mandatory_context_overflow`. Both include a structured reason and
an actionable suggestion. Optional exclusions use stable reason codes such as
`out_of_scope`, `privacy_blocked`, `capability_mismatch`, `duplicate`,
`lower_priority`, `stale`, `over_budget`, `invalid_provenance`, and
`unsupported_type`, `unsupported_scope`, and `invalid_scope`.

Budget calculation reserves system, tools, current user message, conversation,
output, and a safety margin. It uses `tiktoken` for a compatible model when
installed, otherwise it uses the documented conservative UTF-8 byte estimate
`ceil(bytes / 3)`. If the router has no context-window metadata, the manifest
records that fact and allocation uses an 8,192-token cap. The final prompt is
validated with the same estimator after assembly.

Identity/pass-through and exact duplicate merging are available without any
provider call. An extractive sentence transformer is also available as a
pluggable local strategy and requires an explicit per-item opt-in. It refuses
to transform user-authored text. No LLM summarization is performed. Original
and final estimates plus provenance are recorded for each transformation.

## Persistence and privacy

`context_package_compiled` contains item/source IDs, scores, budget metadata,
privacy labels, exclusions, and transformation provenance. It never contains
candidate contents, raw prompts, file text, or hidden reasoning. The trace
payload sanitizer uses a field allowlist. Existing `context_compiled` events
remain available for workspace compiler provenance and compatibility. A run's
manifest is visible from run details and session hydration and survives
LangGraph checkpoint restart/resume.

The Inspector shows budget use, model window, reservations, included objects,
scores, provenance, transformations, exclusions, and per-call manifests across
root/specialist runs. Legacy workspace manifests remain readable. When no
compiled manifest exists, the UI reports that state instead of estimating one.

## Current limits

- The allocator ranks candidates returned by the existing retrieval and graph
  compilers; it does not expand retrieval or alter retrieval thresholds.
- Existing memory-tier safety caps still apply before token allocation.
- Freshness affects ranking when a source has `updated_at`; expiration is the
  only current timestamp-based hard exclusion.
- Token counts are estimates and may differ from provider-native tokenization.
- Conversation history remains part of the required chat transcript. The new
  candidate allocator manages retrieved memory and workspace context, not the
  historical chat-message policy.
