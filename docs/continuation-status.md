# AURA Personal v1 — Operational Status

Updated: 2026-11-21

## Mission and stop condition

Complete the finite release contract in [Product Vision and v1 Roadmap](PRODUCT_VISION_AND_V1_ROADMAP.md). Work only on O1–O7, A1–A8, or a release-blocking defect demonstrated by those scenarios. Stop when P3 passes, publish the v1 evidence report, and tag the accepted commit. After that, use a separately prioritized maintenance/v1.1 backlog; do not keep v1 open for speculative or cosmetic work.

## Current repository state (2026-11-21)

- Repository: [nhatminh-115/Personal](https://github.com/nhatminh-115/Personal)
- Canonical `main`: `8647e5ac208c3076a559bdd5e34c20050d1590e1` (A1 acceptance PR [#390](https://github.com/nhatminh-115/Personal/pull/390) merged after PR #388 and the PR #389 product contract).
- PR #390's exact green head was `34749fb1bc3c5e29590c5a383cccfcdd9715bbd3`; full Actions run [#44913776814](https://github.com/nhatminh-115/Personal/actions/runs/44913776814), job `136874905650`, passed before merge.
- That run completed 770 backend tests in 67.76s with four warnings; Phase 1, 2.1, 3, and 4 passed; frontend 48 files / 328 tests passed; Vite build completed in 9.74s.
- PR #388's exact green head was `44789f6372d9185fe99157338af2cd5f0698a9d4`; full Actions run [#44911360621](https://github.com/nhatminh-115/Personal/actions/runs/44911360621), job `136867681622`, passed before merge.
- That run completed 769 backend tests in 81.05s with four warnings; Phase 1, 2.1, 3, and 4 passed; frontend 48 files / 328 tests passed; Vite build completed in 12.18s and the Docker UI stage in 12.07s.
- Earlier baseline run #1014 tested `cf64f3435b03210f72c40a70ca3158d41362bfcb`, not later code. Do not attribute its counts to current `main`.

## P0 — Trustworthy baseline

PRs #2–#10 were compared with current `main`; all were 551 commits behind and not mergeable. They are closed without merging their stale branches.

| PR | Disposition |
| --- | --- |
| #2 Research graph promotion | Superseded by current Research workspace-object persistence from the delegated Research runtime and regression coverage in `tests/unit/test_memory_assembly_pipeline.py`. |
| #3 Personal Notes persistence | Superseded by Notes stored in the shared workspace graph and the current workspace API/tests. Its standalone Notes route and migration are not the current data model. |
| #4 system-edge deletion protection | Superseded by the current atomic batch deletion endpoint and system-edge regression coverage. |
| #5 Study sessions | Superseded by the current graph-backed Study API and tests; the old standalone migration branch is stale. |
| #6 Automations | Superseded by the current persisted Automations API, outbox/runtime behavior, and `tests/unit/test_automations.py`. |
| #7 Routing Studio semantic coverage | Closed as stale. Current `RoutingStudio.tsx` still needs the session ID/availability effect-dependency fix; carry it into A8 with a prop-change regression. |
| #8 context-compile provenance | Superseded by the current safe `context_compiled` projection and workspace/execution-graph coverage. |
| #9 routing provenance | Superseded by persisted reasoning/fallback events and current execution-graph coverage. |
| #10 system-edge batch deletion | Superseded by current API/UI protections and atomic batch-delete coverage. |

CodeGraph remains optional and pending external setup. It must not be installed or downloaded automatically.

## P1 — Acceptance status

“Implemented” and green CI are not acceptance passes. Complete each scenario against an actual running deployment and save a sanitized report with run/event IDs, route metadata, assertions, and outcomes.

| Scenario | Status | Current evidence / next proof |
| --- | --- | --- |
| A1 Project continuity | **PASS** | Local isolated API-process acceptance on 2026-11-21: created a project and linked Note, previewed and chatted with only that Note selected, stopped and restarted the API, then verified project/Note/transcript/context provenance and foreign-project exclusion. Run `ce21710c-fedd-4da5-a8db-55c28550cbbb`; sanitized report [`docs/acceptance/a1-project-continuity-20261121.json`](acceptance/a1-project-continuity-20261121.json). Used `mock-default`; this is not live-inference evidence. |
| A2 Research to learning | **BLOCKED** | Requires a live model plus live Research providers/network for the complete Research → evidence → verified claim → Study/card/review flow. At the current environment check, no OpenAI key or exact dogfood model override was configured, and Ollama/LM Studio loopback endpoints did not respond. Earlier Context Bridge evidence is partial, not an A2 pass. |
| A3 Governed agent execution | **PASS** | Real Docker acceptance on 2026-11-21: bounded failure control, routing/capability checks, specialist recursion guard, three persisted approvals, expected test failure before the patch, passing sandbox test after the patch, workspace mutation, and parent-child lineage verified. Root run `939dc360-4fe6-4213-8257-c9d09b0160eb`; coding child `bf3fbd25-9422-4b7f-8902-8ea728cf1f64`. Sanitized run/event IDs and route metadata: [`docs/acceptance/a3-governed-execution-20261121.json`](acceptance/a3-governed-execution-20261121.json). Uses mock inference and real Docker sandbox; no live-inference claim. |
| A4 Automation recovery | **PASS** | Two-process local acceptance on 2026-11-21 exercised authenticated webhook delivery and duplicate idempotency, approval-gated write, restart while approval-paused, approval resume, queued cancellation, secret digest storage, and sanitized persisted trace. Report [`docs/acceptance/a4-automation-recovery-20261121.json`](acceptance/a4-automation-recovery-20261121.json), run `25161eb3-cf73-58a5-9057-0a3afe5ce5dd`, event `86344c04-e7ed-4959-8d97-35d937ac1595`; mock provider, no live-inference claim. |
| A5 Privacy boundary | **NOT RUN** | Existing unit tests and routing previews are partial evidence. Produce a consolidated report proving blocked invocations occur before provider/tool calls and explicit file-text/cloud confirmation rules hold. |
| A6 Backup and restore | **NOT RUN** | Perform the documented backup and restore into a clean environment; verify database, checkpoints, workspace files, and representative data. |
| A7 Fresh install and live inference | **BLOCKED** | PR #388 adds the Compose UI/app launch path. A live model still needs a configured provider. No OpenAI key or dogfood model override is configured, and Ollama/LM Studio loopback endpoints did not respond at the current environment check. |
| A8 Everyday workspace use | **NOT RUN** | Use saved Notes, Library, Study, Projects, and Automations across reloads; verify pagination/search/conflict/recovery states. Include the carried Routing Studio session-refresh fix. |

The live dogfood documents record earlier project-memory and Research Context Bridge passes. Preserve those as their own evidence; do not upgrade them to A1 or A2 passes.

## Completed implementation PR

PR #388 packages the production React UI in Docker Compose and serves it from the API origin, with regression coverage for public static assets and protected API/docs routes. It merged as `a609e8625f2583ce7a492a7040691a7b785a522b`. The exact tested head and full CI evidence are recorded above. A7 remains blocked until live inference is exercised with a configured provider.

## Execution order

1. A1 is complete with the committed runner, integration test, and sanitized report.
2. A2 remains BLOCKED by live model and Research-provider/network setup.
3. A3 passed on 2026-11-21 using the real Docker sandbox. The first run exposed that read-only rootfs lacked writable temporary storage for pytest capture; a bounded `/tmp` tmpfs fixed it, and the script now asserts the post-patch sandbox test exits 0.
4. A4 is PASS with duplicate webhook delivery, approval pause/resume across an API process restart, and cancellation evidence.
5. Continue with A5, the next independent non-blocked scenario. Then work on A6 and A8 while A2, A3, and A7 prerequisites remain unavailable.
6. For every demonstrated release-blocking gap, add regression coverage, run targeted checks and the full relevant workflow, open one focused PR, wait for Actions on its exact head, and merge only that tested head.
7. At P3, verify all A1–A8 evidence against one release candidate, complete clean-environment restore, update the docs, and tag AURA Personal v1. Stop there.

## Live setup constraints

- At the latest environment check, `ollama` was installed but `http://127.0.0.1:11434` did not respond. `OPENAI_API_KEY`, `AURA_DOGFOOD_MODEL_OVERRIDE`, and `RESEARCH_PROVIDER_MODE` were unset.
- Live Research also requires `RESEARCH_PROVIDER_MODE=live` and network access to its configured sources. Do not silently substitute a hosted model for a requested local model.
- CodeGraph is not installed/configured and is not a v1 blocker.
- CI is deterministic and must not require paid model access, Ollama, LM Studio, or CodeGraph.
