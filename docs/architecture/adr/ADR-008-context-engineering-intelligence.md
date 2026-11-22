# ADR-008: Deterministic Context Engineering Intelligence

## Status

Accepted

## Context

AURA v1 already had memory retrieval, workspace graph compilation, project and
privacy filtering, capability checks, and safe context traces. It did not
allocate retrieved context against the model selected by the existing router,
rank mixed candidates consistently, or explain optional exclusions and
transformations in the run Inspector.

The new behavior must preserve the established retrieval and routing contracts,
avoid a second model-selection path, keep the current user request and system
policy mandatory, and remain durable across LangGraph restart/resume.

## Decision

Keep `ContextAssembler` and `WorkspaceContextCompiler` as the canonical data
sources. Normalize their outputs to typed runtime `ContextItem` values and pass
them through hard filtering, deterministic priority/score ranking, model-aware
budget allocation, optional local transformation, final prompt-window
validation, and a sanitized `ContextManifest` event.

Call the existing model router exactly once. Mandatory messages and explicitly
selected/required objects contribute to its required-window check. Use the
resulting `ModelSelection.context_window` for final candidate allocation. Use
`tiktoken` only when a compatible encoder is already available; otherwise use
the documented UTF-8-byte estimate and an explicit 8,192-token window fallback
when model metadata is unknown.

User-authored text is never extractively rewritten. Explicitly selected and
required candidates produce actionable errors when policy rejects them or the
budget cannot fit them. Optional context may be excluded with a structured
reason. Initial transformations are identity, exact duplicate merge, and an
opt-in local extractive strategy; no model is called to compile context.

Store content only in run/checkpoint state when durable resume requires it.
Store only IDs and sanitized operational metadata in trace events. For
explicitly selected browser files, keep text in the attachment checkpoint and
use a `content_reference` in the normalized candidate to avoid a second copy.

## Consequences

### Positive

- Existing retrieval, workspace provenance, privacy policy, and routing remain
  authoritative.
- Candidate choice is deterministic and inspectable without hidden reasoning
  or an extra model invocation.
- Selected content cannot silently disappear due to budget or hard policy
  filters.
- Per-run manifests explain use, exclusions, and transformations without
  exposing source text.
- Checkpoint state supports restart/resume while selected file text is stored
  only once.

### Trade-offs

- Token counts are estimates and may differ from provider-native tokenization.
- The allocator does not change retrieval thresholds or the existing memory
  tier caps.
- The 8,192-token fallback is intentionally conservative when model metadata
  is unavailable.
- Conversation transcript trimming remains outside this milestone.
