# AURA Product Vision and AURA Personal v1 Roadmap

**Document status:** Canonical product direction and proposed release contract  
**Last updated:** 2026-11-22
**Repository baseline reviewed:** `main` at `aee2c0cd7c4e84cd32d9d9a099d2db78ea10ad36`
**Target:** AURA Personal v1

This document defines what AURA is being built to become, the product objectives that matter, and the finite acceptance criteria for calling the first personal release complete. It is the source of truth for product intent and release scope. It does not replace technical architecture documents, ADRs, API contracts, or the live-dogfooding instructions.

For implementation details, consult [Current Runtime Architecture](architecture/current-runtime.md). For the difference between deterministic CI and real-provider acceptance, consult [Live Dogfooding](dogfooding.md). The [Autonomous Continuation](continuation-status.md) document is an operational handoff and should remain consistent with this product contract.

---

## 1. Product vision

AURA — Adaptive User Runtime Agent — is a **persistent personal AI workspace and execution runtime**.

AURA helps one person carry work across projects and time: collect and reference material, preserve useful context, investigate questions, turn verified knowledge into learning, and execute approved work through an observable AI runtime.

AURA is not intended to be another ephemeral chatbot. Its defining property is continuity: projects, conversations, selected context, notes, research artifacts, study progress, automations, and execution history should remain connected and recoverable instead of disappearing when a chat ends.

### Product promise

A user should be able to:

1. Return to a project after days or weeks and recover the relevant workspace, conversations, decisions, and explicitly selected context.
2. Ask AURA to work with personal knowledge and project material without silently mixing unrelated projects or bypassing privacy boundaries.
3. Delegate bounded work to specialist runtimes and tools, inspect what happened, and approve consequential actions.
4. Preserve the provenance of research and knowledge so that conclusions can be traced to their supporting sources.
5. Convert useful findings into durable notes and learning activities.
6. Schedule or trigger recurring work and recover its execution state after interruptions.
7. Keep control over external files, provider selection, data transfer, and destructive actions.

### Target user and product boundary

The v1 target is a **single-person, persistent workspace** for someone managing multiple long-running projects and knowledge-work workflows. The default deployment is a local service. AURA can use configured local or hosted model providers; local deployment must not be confused with a guarantee that every provider interaction stays on-device. Privacy and routing policy must govern those boundaries explicitly.

AURA should be useful with a modest, deliberately configured provider set. A large integration catalog is not itself a product goal.

---

## 2. Product model

### Personal workspace

The current application is organized around these personal surfaces:

| Surface | User purpose |
| --- | --- |
| Home | Return to the workspace and see the current working context |
| Library | Reference and search personal files and collections |
| Notes | Capture durable personal knowledge and link it to projects |
| Study | Learn from saved material, maintain sessions, and review learning cards |
| Automations | Configure scheduled or event-triggered routines and inspect their runs |
| Projects | Maintain persistent workspaces for distinct areas of work |

A project is one reusable workspace. Its Overview, Chat, Board, Split, and Files are views within that project, not separate products. Chat and Board are intended to operate on the same persisted project conversation graph.

### Shared knowledge substrate

The Workspace Object Graph is the shared substrate for project conversations, user-authored notes, context bridges, context sets, branches, research artifacts, learning objects, and operational provenance where supported by the current implementation.

The product should preserve the distinction between:

- **Objects:** durable pieces of workspace information or activity.
- **Edges:** explicit relationships and context-flow links between objects.
- **Board layout:** the user's visual arrangement, stored separately from semantic relationships.
- **Compiled context:** the bounded, validated set of objects selected for a particular model turn.
- **Provenance:** a record of which saved objects and relationships informed a run.

The graph is not permission for the model to ingest everything. Context must remain explicitly selected or linked, scoped to the correct project, bounded, and subject to privacy and capability checks.

### Library and external files

The Library is a reference and indexing layer, not an AURA-owned replacement for the user's file system or cloud drive. External files remain where they already live. The current browser-local import flow keeps file content in the browser until the user explicitly chooses an action such as Send text. Only bounded, explicitly selected content should enter a durable run context, and cloud transfer must follow the routing-confirmation and privacy policy.

AURA must not silently upload, copy, or index the full contents of external files merely because a reference exists.

### Agent runtime

AURA uses one root Personal Orchestrator. Specialist runtimes are bounded children delegated by that root; they are not an unconstrained peer swarm. The root remains responsible for task scope, project scope, effective privacy, available capabilities, approvals, and the final outcome.

The runtime should be durable and inspectable: runs, checkpoints, approvals, tool results, cancellation state, and safe execution events must support recovery and diagnosis without exposing hidden reasoning or unnecessarily sensitive payloads.

---

## 3. Product principles

These principles govern implementation trade-offs and future feature proposals.

1. **Continuity over chat volume.** AURA should preserve useful project state and knowledge across sessions; adding more chat UI is not a substitute.
2. **One root orchestrator.** Specialists provide bounded expertise or execution capability under trusted root scope. Do not introduce a general-purpose agent swarm without a demonstrated need.
3. **Explicit context, not indiscriminate retrieval.** The user and workspace relationships determine what may enter a turn. Context compilation must enforce scope, limits, privacy, and provenance.
4. **Durability is a product feature.** Interruption, restart, retry, approval pause, and cancellation are normal operating conditions, not edge cases.
5. **Fail closed on security and privacy.** Unknown capabilities, insufficient provider guarantees, invalid scope, or disallowed data transfer must not silently degrade into a less safe route.
6. **Approvals follow risk.** Read-only work may proceed under policy; consequential writes, external side effects, and destructive actions require the applicable authorization.
7. **Evidence and provenance matter.** Research claims, context handoffs, and execution outcomes should be traceable to their sources without pretending that an unverified claim is verified.
8. **External content is data, not authority.** Tool output, retrieved documents, connected sources, and model-supplied metadata cannot override AURA policy or authorize unrelated actions.
9. **User-authored content remains user-owned.** AURA must not silently rewrite or discard notes, project content, or drafts. Conflicts should be surfaced and resolved explicitly.
10. **No silent provider substitution.** Provider capability and reasoning support must be based on declared or observed evidence, not guessed from model names. Fallback behavior must follow the saved policy.
11. **Bounded resource use.** File parsing, tool execution, model discovery, responses, pagination, and backup/restore must have explicit limits.
12. **Build for demonstrated workflows.** New architecture or integrations need a user-visible use case, a measurable acceptance condition, and a reason existing primitives are insufficient.

---

## 4. V1 objectives

The status labels below describe the repository baseline reviewed on 2026-11-21. “Implemented” means the capability exists in the codebase; it does **not** mean every real-world acceptance scenario has passed.

### O1 — Durable personal agent runtime

**Outcome:** AURA can execute bounded multi-step work, pause for authorization, survive process interruption, and provide a trustworthy record of the outcome.

Current implementation includes a LangGraph root runtime, persisted run state and checkpoints, approval and routing-confirmation flows, cancellation handling, event-driven execution, specialist delegation, and execution history.

**V1 acceptance criteria**

- A run can be created, inspected, completed, failed, or cancelled with a persisted terminal state.
- An approval-gated run can pause, survive an API process restart, and resume from its persisted checkpoint after an explicit decision.
- Duplicate delivery or client retry does not execute the same admitted turn or event twice where the idempotency contract applies.
- Cancellation is persisted and observed at documented safe boundaries; the UI does not claim that an in-flight provider or tool call can always be interrupted.
- Specialist delegation preserves trusted root scope, project scope, privacy, and capability restrictions. Model-supplied delegation arguments cannot widen them.
- Execution history explains operational events and outcomes without exposing hidden chain-of-thought, raw prompts, tool arguments, or raw tool output in telemetry.

**Baseline status:** Core runtime and deterministic verification are implemented. Release acceptance still requires a consolidated restart/approval/retry/cancellation scenario against a running deployment.

### O2 — Explicit model routing and capability governance

**Outcome:** AURA selects a provider and model according to task requirements, privacy, capability, and user policy, rather than treating all models as interchangeable.

Current implementation includes a provider-neutral ModelRouter, typed routing context, scoped routing profiles, provider capability metadata, capability-based tool registration, and persisted routing decisions.

**V1 acceptance criteria**

- Every model call passes through the routing layer and records the effective route and relevant policy snapshot.
- System, project, and session routing settings resolve predictably; stale concurrent edits cannot overwrite newer profiles.
- Required capabilities are satisfied only by explicitly registered providers/tools. Unknown support is not treated as supported.
- Local-only and confidential constraints prevent disallowed cloud model, embedding, research, or tool paths **before** data is sent.
- Fallback and cloud transfer behavior follow the user's effective policy and required confirmation flow.
- At least one user-configured local or hosted inference provider completes a representative root workflow and a specialist workflow without an undocumented fallback.

**Baseline status:** Routing and capability controls are implemented. A7 passed on 2026-11-22: a clean Compose deployment completed live root and Coding Specialist runs with persisted `ollama:aura-qwen3-coding:4b-8k` decisions for both roles. The sanitized report is [`docs/acceptance/a7-fresh-install-20261122.json`](acceptance/a7-fresh-install-20261122.json). Privacy-boundary acceptance remains separately recorded under A5.

### O3 — Unified persistent workspace

**Outcome:** Projects, conversations, notes, files, and visual organization behave as connected views of durable workspace state.

Current implementation includes saved projects, a shared object/edge graph, project Chat and Board projections, personal Notes, Library references, context bridges/sets, execution provenance, bounded pagination, revision checks, and layout persistence.

**V1 acceptance criteria**

- A user can create, reopen, archive, and restore a project without losing its persisted objects or conversation history.
- Chat and Board show consistent persisted project state; changes to user-authored objects and layout survive reload.
- A user can link a personal Note or Library reference to a project, select permitted context for a chat, and inspect the context preview before invocation.
- Context compilation includes only in-scope, explicitly selected or linked sources and records a safe provenance manifest.
- Stale writes produce a conflict instead of silently overwriting newer content.
- Pagination, search, empty states, and retry paths work on saved data rather than relying on demo fixtures.

**Baseline status:** The graph and principal workspace surfaces are implemented and covered by CI. Full cross-surface acceptance remains part of live dogfooding.

### O4 — Traceable knowledge and learning lifecycle

**Outcome:** AURA can preserve research provenance and help a user turn supported findings into durable learning material.

Current implementation includes Research source/evidence/claim objects, provenance relationships, Research Radar, Notes, Study sessions, reflections, learning cards, and a review queue.

**V1 acceptance criteria**

- A live Research run can preserve source, evidence, and claim lineage in the correct project.
- Verification status is explicit. A qualified or unsupported claim cannot be treated as a verified finding or start the verified-claim Study flow.
- Research Radar reads the saved project artifacts and opens them at their persisted Board objects; it does not invent relationships or silently rewrite artifacts.
- A verified claim can start a Study session linked back to its source project object.
- Learning cards, review counts, next-review dates, and reflections persist across reloads. Stale edits/reviews surface revision conflicts.
- The user can follow the chain from source to evidence to claim to learning object.

**Baseline status:** The data model and UI flows are implemented. A live Research Context Bridge scenario has passed. The full live prior-art investigation scenario is documented but is not recorded as an acceptance pass in the current dogfooding report.

### O5 — Durable, governed automations

**Outcome:** AURA can trigger useful recurring or event-driven work without losing its schedule, approval state, or execution history.

Current implementation includes a transactional event outbox, persistent scheduler, one-shot and recurring jobs, webhook triggers, approval integration, cooperative cancellation, retry/dead-letter handling, and run history.

**V1 acceptance criteria**

- A scheduled or webhook-triggered event creates a traceable AURA run with its origin preserved.
- Duplicate webhook event IDs return the original event rather than creating duplicate work.
- A queued event and an approval-paused or running workflow behave correctly across a process restart.
- Paused and archived automations reject new triggers as specified; archiving preserves history.
- A user can inspect, cancel, retry, and understand the state and limitations of an automation run.
- Webhook request bodies do not become untrusted prompt instructions; webhook secrets are returned only at creation and stored as digests.

**Baseline status:** The automation runtime and associated tests are implemented. A4 passed on 2026-11-21 using two isolated local API processes: duplicate authenticated webhook delivery, approval-gated write, restart while approval-paused, resume, queued cancellation, digest-only secret storage, and persisted trace were verified. The sanitized report is [`docs/acceptance/a4-automation-recovery-20261121.json`](acceptance/a4-automation-recovery-20261121.json). This deterministic run does not claim live inference.

### O6 — Security, privacy, and recoverability

**Outcome:** AURA protects the user's workspace and makes recovery practical.

Current implementation includes capability permissions, approval gates, a constrained Docker execution sandbox, workspace path confinement, prompt-injection defenses, provider and tool error redaction, optional shared API bearer authentication, bounded inputs/responses, and local/Compose backup procedures.

**V1 acceptance criteria**

- Workspace tools cannot escape the configured workspace root through traversal, absolute paths, symlinks, or junctions.
- The default Docker coding sandbox runs with its documented restrictions, including no network access, resource limits, a non-root user, and approval-gated high-risk execution.
- Untrusted tool and retrieved content cannot override system policy, change the task, expose secrets, or authorize unrelated side effects.
- Privacy restrictions are verified at the provider boundary, not only in UI labels or routing previews.
- A backup can be restored into a clean environment with the database, LangGraph checkpoints, and workspace files required by that deployment.
- Network-exposed deployments follow the documented authentication and TLS requirements. The shared bearer token is an access gate, not multi-user identity or tenant isolation.
- Operational traces and error messages do not leak prompts, credentials, raw provider bodies, or hidden reasoning.

**Baseline status:** Security controls and backup tooling are present. A clean-environment restore drill and consolidated privacy-boundary acceptance are required before v1.

### O7 — Usable, real-world personal workflow

**Outcome:** AURA is useful in repeated work, not merely a collection of passing unit tests.

**V1 acceptance criteria**

- The primary Home, Library, Notes, Study, Automations, and Projects surfaces load saved state and expose clear loading, empty, error, retry, and conflict states.
- A new installation can be configured by following the repository documentation without relying on undocumented manual steps.
- At least one representative workflow is completed end-to-end with a real configured model provider. Deterministic/mock verification remains valuable but is not counted as live-provider acceptance.
- The user can inspect what AURA used, what it changed, what it did not do, and what still requires approval.
- No release-blocking data-loss, privacy-boundary, authorization, or duplicate-execution defect remains open.

**Baseline status:** A1, A3–A8 have recorded acceptance passes. A7 passed on 2026-11-22 with a fresh Compose PostgreSQL volume, served production UI, and completed local root-to-specialist inference. A2 remains the outstanding workflow before the product-level release review.

---

## 5. Required v1 acceptance scenarios

These scenarios are the release evidence. A green CI run is necessary but not sufficient.

| ID | Scenario | Required evidence | Current outcome |
| --- | --- | --- |
| A1 | Project continuity | Create a project, link a Note, start a chat with selected context, inspect the preview/provenance, restart the service, reopen the project, and verify persisted state and scope. | **PASS** — [`a1-project-continuity-20261121.json`](acceptance/a1-project-continuity-20261121.json) |
| A2 | Research to learning | Run live Research, inspect source/evidence/claim lineage, confirm verification gates, start Study from a verified claim, create/review a card, and verify its persisted schedule and source link. | **INCOMPLETE** — full live Research-to-Study/card/review flow still needs acceptance evidence. |
| A3 | Governed agent execution | Run a bounded specialist task in the sandbox, request a consequential write, verify approval is required, approve or reject it, and inspect the persisted result and safe execution trace. | **PASS** — [`a3-governed-execution-20261121.json`](acceptance/a3-governed-execution-20261121.json) |
| A4 | Automation recovery | Trigger a scheduled or webhook routine, exercise duplicate delivery, approval, cancellation or retry, restart at a meaningful boundary, and verify that history and event/run identity remain consistent. | **PASS** — [`a4-automation-recovery-20261121.json`](acceptance/a4-automation-recovery-20261121.json) |
| A5 | Privacy boundary | Attempt representative local-only/confidential workflows and verify disallowed cloud model, embedding, research, and tool calls are blocked before invocation. Verify explicit file-text transfer and cloud confirmation behavior. | **PASS** — [`a5-privacy-boundary-20261121.json`](acceptance/a5-privacy-boundary-20261121.json) |
| A6 | Backup and restore | Create a backup using the documented deployment-specific procedure, restore into a clean environment, and verify the database, checkpoints, workspace files, and representative user data. | **PASS** — [`a6-clean-restore-20261121.json`](acceptance/a6-clean-restore-20261121.json) |
| A7 | Fresh installation and live inference | Follow the documented setup from a clean checkout, verify readiness and UI access, configure one supported provider, and complete one root plus one specialist workflow without silent provider substitution. | **PASS** — [`a7-fresh-install-20261122.json`](acceptance/a7-fresh-install-20261122.json) |
| A8 | Everyday workspace use | Use Notes, Library, Study, Projects, and Automations with saved data; reload the UI and confirm pagination, search, conflicts, and recovery states remain understandable. | **PASS** — [`a8-everyday-workspace-20261121.json`](acceptance/a8-everyday-workspace-20261121.json) |

For each scenario, retain a sanitized report containing run IDs, event IDs, selected route metadata, acceptance assertions, and outcomes. Do not store prompts, secrets, raw source text, or model responses in the report unless a separate, explicit debugging process requires them and the data is protected.

### Live dogfooding evidence at the reviewed baseline

The current [Live Dogfooding](dogfooding.md) report records:

- **Project memory retrieval — passed:** a local Ollama run retrieved the target project's two-person-review/rollback rule and excluded a foreign-project decoy.
- **Research Context Bridge merge — passed:** a local Ollama run delegated to Research, persisted a verified claim, created a durable Context Bridge, and compiled a fresh chat using that Bridge as its only selected object.
- **Fresh installation and live inference (A7) — passed:** a fresh Docker Compose project migrated a new PostgreSQL volume, served the production UI, and completed a root-to-Coding-Specialist workflow. Both runs persisted the exact local Ollama model selection; no hosted provider was called. See [`docs/acceptance/a7-fresh-install-20261122.json`](acceptance/a7-fresh-install-20261122.json).
- **Routing constraints preview — passed:** local-only/cloud-allowed preview policies were preserved and the preview made zero model calls. This is policy-preview evidence, not live inference evidence.
- **Research to learning (A2) — incomplete:** earlier live Research/Context Bridge dogfood proves a verified claim can be created, but the complete Study session, learning card, review schedule, and source-link chain still need one end-to-end report.
- **Coding impact / CodeGraph — not run:** the optional CodeGraph provider is not installed or configured. It must not be installed automatically and is not a v1 blocker.

Do not convert “script exists,” “preflight succeeded,” “CI passed,” or “scenario did not run” into a live acceptance pass.

---

## 6. Release roadmap

The roadmap is deliberately finite. Each phase has an exit condition; work should not continue merely because another possible improvement can be imagined.

### P0 — Establish the product contract and a trustworthy baseline

**Purpose:** Make product intent and repository state unambiguous.

- Keep this document as the canonical product/release contract.
- Keep the README, Current Runtime Architecture, Live Dogfooding, and Autonomous Continuation documents consistent with the actual main branch.
- Reconcile stale continuation notes and old open pull requests. Review each old PR's unique diff before closing it; do not merge historical branches simply because they are open.
- Record the exact main commit and exact GitHub Actions run used as the baseline.

**Exit condition:** A new contributor or coding agent can identify the product goal, current implementation state, next acceptance scenario, and authoritative technical documents without relying on chat history.

### P1 — Complete end-to-end dogfooding

**Purpose:** Prove that existing subsystems work together in real workflows.

Priority order:

1. Project continuity and context restoration.
2. Live Research to verified claim to Study.
3. Approval-gated specialist execution and restart recovery.
4. Automation event recovery and duplicate-delivery behavior.
5. Privacy-boundary checks at actual provider/tool invocation points.
6. Backup and restore into a clean environment.
7. Fresh installation and live inference.

Use the existing dogfooding scripts and extend them only when a missing acceptance assertion cannot be represented. Keep reports sanitized and reproducible.

**Exit condition:** A1–A8 have explicit pass/fail evidence. Any scenario blocked by external setup is marked blocked/not run, never passed.

### P2 — Close demonstrated product gaps

**Purpose:** Fix issues revealed by P1, not invent unrelated architecture.

- Prioritize data loss, incorrect context, privacy violations, authorization bypasses, duplicate side effects, failed recovery, and misleading UI states.
- Fix usability problems that prevent completion of an acceptance scenario.
- Improve documentation where a clean installation or recovery drill exposed ambiguity.
- Reassess optional integrations only when a concrete workflow needs them.
- Record deferred ideas separately rather than expanding v1 scope.

**Exit condition:** All release-blocking findings from P1 are fixed or explicitly accepted as documented limitations. The acceptance scenarios pass again on the candidate commit.

### P3 — Release readiness and v1 freeze

**Purpose:** Ship a coherent, recoverable personal product.

- Run the full required GitHub Actions workflow on the exact release candidate.
- Complete the clean-environment backup/restore drill.
- Review security, privacy, provider configuration, migrations, and network-exposure documentation.
- Publish concise setup, operation, backup, restore, and known-limitations documentation.
- Tag the accepted commit as AURA Personal v1.

**Exit condition:** All mandatory acceptance scenarios pass on the tagged commit, no release-blocking defect remains open, and the user can install, operate, and recover the product using documented procedures.

After v1, switch to maintenance and a separately prioritized v1.1 backlog. Do not keep the v1 milestone open for cosmetic improvements or speculative integrations.

---

## 7. Explicit non-goals for v1

The following are not required to ship AURA Personal v1:

- A multi-tenant SaaS platform, account system, organization management, or tenant isolation.
- An unrestricted autonomous desktop/browser agent that can act without scoped tools and approvals.
- A peer-to-peer swarm of autonomous agents.
- A replacement for GitHub, Google Drive, the user's file system, Notion, or a full IDE.
- Silent ingestion of every connected file or folder.
- A global semantic search engine or AI question-answering layer over every external file. Current search is scoped to persisted workspace objects and indexed metadata; content transfer remains explicit.
- A large plugin/provider marketplace.
- Mandatory CodeGraph installation. CodeGraph remains an optional external integration.
- A general-purpose visual canvas product. The Board exists to inspect and organize the shared project graph.
- Unbounded feature development under an “autonomous continuation” loop.

These may be reconsidered after v1 only when a real user workflow, security model, and acceptance criterion justify them.

---

## 8. Deferred decisions

Keep these decisions explicit; do not silently turn them into implementation assumptions.

| Topic | V1 position | Revisit when |
| --- | --- | --- |
| Multi-user identity and tenant isolation | Out of scope; single-user local deployment | A real shared deployment requirement exists |
| Global semantic search / AI answers | Deferred; current search is bounded and metadata/object-oriented | Users repeatedly need answers across large saved corpora and a privacy-safe retrieval design is validated |
| Full document vault / cloud sync | Out of scope; Library references existing files | A concrete ownership, sync, and conflict model is proposed |
| CodeGraph | Optional, not a release gate | A coding workflow requires graph-based repository impact analysis |
| More specialist types/providers | Add only when existing runtime capabilities cannot serve a demonstrated task | A repeatable workflow has a clear capability gap |
| Native desktop application | Not required for v1 | Browser/local workflow limitations are demonstrated in actual use |

---

## 9. Development and autonomous-agent operating contract

Any coding agent (including Codex or a future assistant) working on AURA should follow this contract:

1. Read this document, [Current Runtime Architecture](architecture/current-runtime.md), [Live Dogfooding](dogfooding.md), and the current [Autonomous Continuation](continuation-status.md) before proposing a milestone.
2. Inspect the actual current branch, working tree, tests, and relevant implementation. Do not assume that a previous chat summary or an old continuation note is current.
3. Tie every change to one objective (O1–O7), one acceptance scenario (A1–A8), or a concrete release-blocking defect.
4. State the user-visible problem, current behavior, intended behavior, and test/acceptance evidence before implementation.
5. Prefer the smallest change that closes the demonstrated gap. Do not add a framework, provider, abstraction, or agent role for novelty.
6. Preserve security, privacy, project scope, idempotency, durability, and user-authored content invariants.
7. Add regression tests for the failure mode. Run targeted checks, then the relevant full verification workflow.
8. Keep work isolated on a fresh branch from canonical main. Report the exact tested head SHA and remote CI run. Do not claim success from an unverified local result.
9. Never merge a PR unless explicitly authorized by the repository owner or the task's stated operating policy.
10. If no meaningful gap remains, external setup is required, or the next step would expand scope without user value, stop and report the blocker or recommendation. Do not manufacture work to keep the loop running.

### Definition of “done” for an individual milestone

A milestone is done only when:

- Its acceptance condition is written and testable.
- The implementation and regression coverage are complete.
- Relevant deterministic and integration checks pass.
- Any required live dogfood has an explicit acceptance result.
- The exact remote CI run passes on the exact proposed commit.
- Documentation and known limitations are updated.
- The next step is either another justified objective or an explicit stop.

---

## 10. Baseline snapshot and known documentation drift

This section records what was observed when this document was drafted. It is a dated snapshot, not a claim that the repository will never change.

### Repository and CI snapshot

- Repository: [nhatminh-115/Personal](https://github.com/nhatminh-115/Personal)
- Reviewed main commit: **cf64f3435b03210f72c40a70ca3158d41362bfcb**
- Latest reviewed merged milestone: [PR #387 — Validate API token syntax](https://github.com/nhatminh-115/Personal/pull/387)
- Latest reviewed GitHub Actions run: [#1014](https://github.com/nhatminh-115/Personal/actions/runs/44906302886), completed successfully on the reviewed main commit.
- Recorded verification: 767 backend tests passed; Phase 2.1, Phase 3, and Phase 4 vertical-slice verifications passed; 48 frontend test files with 328 tests passed; Vite production build completed. The backend run reported four warnings. These are CI results, not a substitute for A1–A8 live acceptance.

### Implemented capability areas observed in the repository

The reviewed source and documentation contain implementations for the root orchestration runtime, durable execution/checkpointing, multi-tier memory, provider-neutral routing, capability and approval controls, MCP tool discovery, sandboxed execution, persistent scheduling and event delivery, workspace projects and graph, context compilation and provenance, Notes, Library references, Study, Research artifacts and Research Radar, Automations, and backup/restore procedures.

This inventory is intentionally high-level. The technical source of truth is [Current Runtime Architecture](architecture/current-runtime.md); feature existence does not imply that every v1 acceptance scenario has passed.

### Known gaps and caveats at this snapshot

- The current [Autonomous Continuation](continuation-status.md) file still names the older main commit **61e72cc72276cc16bde8eb3952734cdac2355f31** and stops its recent milestone list at PR #386. It must be synchronized with the reviewed main baseline before it is used as a current operational handoff.
- The [Live Dogfooding](dogfooding.md) file distinguishes passed local-provider scenarios from scenarios that are not run. Preserve that distinction.
- CodeGraph is an optional external dependency and is not installed/configured in the recorded environment. Do not download or install it automatically.
- The repository had historical open PRs #2–#10 when reviewed. Their branches are substantially behind main. Review each PR's unique changes before closing; do not merge them without a fresh comparison and a demonstrated reason.
- The current shared API bearer token, when configured, is an access gate. It is not user identity, multi-user authorization, or tenant isolation.
- Current Library search indexes saved reference metadata and workspace objects; it does not imply full-text semantic search across all referenced files.

---

## 11. Source-of-truth map

| Question | Authoritative document |
| --- | --- |
| What is AURA and what does v1 mean? | **This document** |
| How does the current runtime work? | [Current Runtime Architecture](architecture/current-runtime.md) |
| What architecture decisions are intentional? | [Architecture Decision Records](architecture/adr/) and [System Architecture](architecture/system.md) |
| Which live workflows have actually passed? | [Live Dogfooding](dogfooding.md) |
| What should the next coding session inspect or execute? | [Autonomous Continuation](continuation-status.md) |
| How do I install, configure, test, back up, and restore AURA? | [README](../README.md), [Compose backup](compose-backup.md), and [Local backup](local-backup.md) |

If two documents disagree about product intent or v1 scope, this document wins. If they disagree about current implementation behavior, inspect the code and update the technical documentation; this product document must not be used to override implementation evidence.
