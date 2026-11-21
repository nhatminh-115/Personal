# AURA Personal v1 — Operational Status

Updated: 2026-11-22

## Mission and stop condition

Complete the finite release contract in [Product Vision and v1 Roadmap](PRODUCT_VISION_AND_V1_ROADMAP.md). Work only on O1–O7, A1–A8, or a release-blocking defect demonstrated by those scenarios. Stop when P3 passes, publish the v1 evidence report, and tag the accepted commit. After that, use a separately prioritized maintenance/v1.1 backlog; do not keep v1 open for speculative or cosmetic work.

## Repository state at start of A2 closeout (2026-11-22)

- Repository: [nhatminh-115/Personal](https://github.com/nhatminh-115/Personal)
- Canonical `main` at the start of this closeout: `aee2c0cd7c4e84cd32d9d9a099d2db78ea10ad36` (PR [#398](https://github.com/nhatminh-115/Personal/pull/398) merged after exact-head CI; parent `42f1f8c6fe354cec64798c55e303097ad0492dd4`). PR #400 is the current release-candidate change from that base.
- PR [#397](https://github.com/nhatminh-115/Personal/pull/397) made empty model responses fail truthfully; exact-head Actions run [#44930471247](https://github.com/nhatminh-115/Personal/actions/runs/44930471247), job `136925752700`, passed; merged before PR #398.
- PR #398 fixed PostgreSQL delegation insertion ordering and added a real-PostgreSQL regression. Exact tested head `ff0c025ca9aeb1123e4bc92dcd853f34857760e9`; Actions run [#44931924075](https://github.com/nhatminh-115/Personal/actions/runs/44931924075), job `136930207418`, passed; merged as `aee2c0cd7c4e84cd32d9d9a099d2db78ea10ad36`.
- PR [#392](https://github.com/nhatminh-115/Personal/pull/392) closed the Docker sandbox temporary-storage gap; exact-head Actions run [#44920179781](https://github.com/nhatminh-115/Personal/actions/runs/44920179781), job `136894288628`, passed.
- PR [#393](https://github.com/nhatminh-115/Personal/pull/393) closed the explicit-provider privacy bypass; exact-head Actions run [#44921277243](https://github.com/nhatminh-115/Personal/actions/runs/44921277243), job `136897630752`, passed.
- PR #394 verified clean-volume backup restoration; exact-head Actions run [#44923216657](https://github.com/nhatminh-115/Personal/actions/runs/44923216657), job `136903540122`, passed.
- PR #395 completed A8 on exact head `0daa66487bee01076e32cb7e03a69046fdd665bd`; full Actions run [#44925681798](https://github.com/nhatminh-115/Personal/actions/runs/44925681798), job `136911117433`, passed before merge.
- That run completed 807 backend tests in 73.52s with four warnings; A6 restore and A8 Compose acceptance passed; Phases 1, 2.1, 3, and 4 passed; frontend 48 files / 329 tests passed; Vite build completed in 9.75s.
- PR #390's exact green head was `34749fb1bc3c5e29590c5a383cccfcdd9715bbd3`; full Actions run [#44913776814](https://github.com/nhatminh-115/Personal/actions/runs/44913776814), job `136874905650`, passed before merge.
- That run completed 770 backend tests in 67.76s with four warnings; Phase 1, 2.1, 3, and 4 passed; frontend 48 files / 328 tests passed; Vite build completed in 9.74s.
- PR #388's exact green head was `44789f6372d9185fe99157338af2cd5f0698a9d4`; full Actions run [#44911360621](https://github.com/nhatminh-115/Personal/actions/runs/44911360621), job `136867681622`, passed before merge.
- That run completed 769 backend tests in 81.05s with four warnings; Phase 1, 2.1, 3, and 4 passed; frontend 48 files / 328 tests passed; Vite build completed in 12.18s and the Docker UI stage in 12.07s.
- Earlier baseline run #1014 tested `cf64f3435b03210f72c40a70ca3158d41362bfcb`, not later code. Do not attribute its counts to current `main`.

## P0 — Trustworthy baseline

At this review, PRs #2–#10 were compared with the canonical `main` above; all were 551 commits behind and not mergeable. They are closed without merging their stale branches.

| PR | Disposition |
| --- | --- |
| #2 Research graph promotion | Superseded by current Research workspace-object persistence from the delegated Research runtime and regression coverage in `tests/unit/test_memory_assembly_pipeline.py`. |
| #3 Personal Notes persistence | Superseded by Notes stored in the shared workspace graph and the current workspace API/tests. Its standalone Notes route and migration are not the current data model. |
| #4 system-edge deletion protection | Superseded by the current atomic batch deletion endpoint and system-edge regression coverage. |
| #5 Study sessions | Superseded by the current graph-backed Study API and tests; the old standalone migration branch is stale. |
| #6 Automations | Superseded by the current persisted Automations API, outbox/runtime behavior, and `tests/unit/test_automations.py`. |
| #7 Routing Studio semantic coverage | Closed as stale. The remaining session ID/availability prop-change coverage is deferred to v1.1 unless a concrete v1 routing or privacy failure is demonstrated; A8 is already accepted. |
| #8 context-compile provenance | Superseded by the current safe `context_compiled` projection and workspace/execution-graph coverage. |
| #9 routing provenance | Superseded by persisted reasoning/fallback events and current execution-graph coverage. |
| #10 system-edge batch deletion | Superseded by current API/UI protections and atomic batch-delete coverage. |

CodeGraph remains optional and pending external setup. It must not be installed or downloaded automatically.

## P1 — Acceptance status

“Implemented” and green CI are not acceptance passes. Complete each scenario against an actual running deployment and save a sanitized report with run/event IDs, route metadata, assertions, and outcomes.

| Scenario | Status | Current evidence / next proof |
| --- | --- | --- |
| A1 Project continuity | **PASS** | Local isolated API-process acceptance on 2026-11-21: created a project and linked Note, previewed and chatted with only that Note selected, stopped and restarted the API, then verified project/Note/transcript/context provenance and foreign-project exclusion. Run `ce21710c-fedd-4da5-a8db-55c28550cbbb`; sanitized report [`docs/acceptance/a1-project-continuity-20261121.json`](acceptance/a1-project-continuity-20261121.json). Used `mock-default`; this is not live-inference evidence. |
| A2 Research to learning | **PASS** | Live root-to-Research run `0a7220ef-4f9e-4f24-9fc9-515d3988a263` and child `a2536102-ab5a-4bd2-815d-c6cbaed32dde` completed with exact Ollama routing. Search, read, evidence extraction, and verified-claim tools succeeded. Study session `553a13d2-9c08-4e4d-af60-707b26fa6549` and reviewed card `35cc32e1-f64a-40c7-85c8-ff31c4b31f52` were linked to that claim and survived an API restart. The result correctly reports `insufficient_evidence` for a broad gap conclusion while retaining one source-backed verified claim. Sanitized report [`docs/acceptance/a2-research-to-learning-20261122.json`](acceptance/a2-research-to-learning-20261122.json). |
| A3 Governed agent execution | **PASS** | Real Docker acceptance on 2026-11-21: bounded failure control, routing/capability checks, specialist recursion guard, three persisted approvals, expected test failure before the patch, passing sandbox test after the patch, workspace mutation, and parent-child lineage verified. Root run `939dc360-4fe6-4213-8257-c9d09b0160eb`; coding child `bf3fbd25-9422-4b7f-8902-8ea728cf1f64`. Sanitized run/event IDs and route metadata: [`docs/acceptance/a3-governed-execution-20261121.json`](acceptance/a3-governed-execution-20261121.json). Uses mock inference and real Docker sandbox; no live-inference claim. |
| A4 Automation recovery | **PASS** | Two-process local acceptance on 2026-11-21 exercised authenticated webhook delivery and duplicate idempotency, approval-gated write, restart while approval-paused, approval resume, queued cancellation, secret digest storage, and sanitized persisted trace. Report [`docs/acceptance/a4-automation-recovery-20261121.json`](acceptance/a4-automation-recovery-20261121.json), run `25161eb3-cf73-58a5-9057-0a3afe5ce5dd`, event `86344c04-e7ed-4959-8d97-35d937ac1595`; mock provider, no live-inference claim. |
| A5 Privacy boundary | **PASS** | 17 targeted checks passed on 2026-11-21. Cloud model, embedding, research, and capability paths were blocked before invocation; selected file text entered checkpoint context but stayed out of traces; the cloud route paused for durable confirmation and rejection made zero provider calls. Sanitized report [`docs/acceptance/a5-privacy-boundary-20261121.json`](acceptance/a5-privacy-boundary-20261121.json), run `1fb9065a-2406-476a-a66a-72ade85d5140`, confirmation `bf203875-3d03-4707-a109-2d7653485b70`. Uses provider spies; no live inference. |
| A6 Backup and restore | **PASS** | Real Docker Compose restore on 2026-11-21 into newly created empty volumes. The verified format-v2 archive restored the completed PostgreSQL run, all 10 LangGraph checkpoint rows for that run, and the workspace file byte-for-byte; all three were confirmed absent before restore. Run `6fa0268e-7ef1-42f8-b795-15f1983ba669`; sanitized report [`docs/acceptance/a6-clean-restore-20261121.json`](acceptance/a6-clean-restore-20261121.json). Uses mock inference and makes no live-inference claim. |
| A7 Fresh install and live inference | **PASS** | Fresh project `aura-a7-v1-clean` was built from canonical main `aee2c0cd7c4e84cd32d9d9a099d2db78ea10ad36` using the documented Docker Compose file and a new PostgreSQL volume. Alembic migrations and `/ready` passed; production UI and built JavaScript asset returned HTTP 200. Root run `7b47edb9-9879-4899-8e27-82ae72f24eaf` delegated to completed Coding Specialist child `44a5d7b5-f402-4449-a88e-0390dda03b4a`; persisted route events show both used exact `ollama:aura-qwen3-coding:4b-8k` with no hosted calls. Sanitized report: [`docs/acceptance/a7-fresh-install-20261122.json`](acceptance/a7-fresh-install-20261122.json). |
| A8 Everyday workspace use | **PASS** | PR #395 merged as `240001a8615a65a6846205249e2b5038875a5b7c`. Real isolated Docker Compose acceptance on 2026-11-21 created and reopened Projects, Notes, Library references, Study session/cards, and Automations across an API restart. Twenty assertions passed across pagination, search, revision conflicts, review state, archive/restore, project graph, layout, and recovery. Uses mock providers and made zero external provider calls. Sanitized report [`docs/acceptance/a8-everyday-workspace-20261121.json`](acceptance/a8-everyday-workspace-20261121.json), source commit `ed9a46047b32c0b79ee3f947aad9ef8ce200508e`. The carried Routing Studio session-refresh regression passed 28/28 targeted frontend tests. Exact full CI: run `44925681798`, job `136911117433`. |

The live dogfood documents record earlier project-memory and Research Context Bridge passes. Preserve those as their own evidence; do not upgrade them to A1 or A2 passes.

## Completed implementation PR

PR #388 packages the production React UI in Docker Compose and serves it from the API origin, with regression coverage for public static assets and protected API/docs routes. PR #398 fixed the PostgreSQL delegation FK ordering exposed by the Compose run. A7 is now a recorded pass; its sanitized fresh-install report is linked above.

## P3 — Release-readiness audit

| Gate | Status | Evidence |
| --- | --- | --- |
| Required CI on the release candidate | **PR #400 CHECKS REQUIRED BEFORE MERGE** | The Research Inspector terminal-status fix passed the full workflow on exact code head `abf8e1355679047f68683226bd957591b3ec8fff`, run `44935743242`, job `136941847025`. The A2 evidence/docs update is on [PR #400](https://github.com/nhatminh-115/Personal/pull/400), and its final exact head must pass the same workflow before merge. |
| Clean-environment backup and restore | **PASS** | A6 restored PostgreSQL, LangGraph checkpoints, and workspace files into empty volumes; the same Compose restore ran again in PR #395 CI. |
| Security, privacy, provider, migration, and network configuration review | **REVIEWED** | Compose publishes API/Postgres only on loopback; credentials are passed to the API container, not the web bundle; defaults remain mock/deterministic; Compose startup migrates to Alembic head; backup restore requires an explicit replace flag and documents rollback/failure behavior. No additional P3 blocker found in this review. |
| Live provider acceptance | **A1–A8 PASS** | A2 and A7 both passed with the exact installed local Ollama model and no hosted model calls. A2’s broad research result remains `insufficient_evidence`; its verified claim is explicitly source-backed and eligible for Study. |

README, Compose backup/restore, and local backup/restore instructions were checked against current behavior. For Docker-based Ollama, the documented host endpoint is `host.docker.internal`; keep provider credentials in local environment/secret storage and out of chat and Git.

## Execution order

1. A1 is complete with the committed runner, integration test, and sanitized report.
2. A2 passed on the persisted live chain recorded in [`docs/acceptance/a2-research-to-learning-20261122.json`](acceptance/a2-research-to-learning-20261122.json). A follow-up replay after the Inspector fix returned `empty_model_response`; it is recorded as a non-acceptance attempt and does not replace the earlier complete pass.
3. A3 passed on 2026-11-21 using the real Docker sandbox. The first run exposed that read-only rootfs lacked writable temporary storage for pytest capture; a bounded `/tmp` tmpfs fixed it, and the script now asserts the post-patch sandbox test exits 0.
4. A4 is PASS with duplicate webhook delivery, approval pause/resume across an API process restart, and cancellation evidence.
5. A5, A6, and A8 passed on 2026-11-21. PR #395 merged as `240001a8615a65a6846205249e2b5038875a5b7c` after exact-head CI passed. A7 passed on 2026-11-22 from a fresh Compose/PostgreSQL install using local Ollama.
6. The P3 documentation/configuration audit and clean restore are complete. The only remaining release action is to wait for PR #400’s final exact-head CI, merge that tested head, and tag the accepted main commit `aura-personal-v1`.
7. Once that tag is created, stop v1 work. Put any later maintenance or v1.1 ideas in a separate backlog.

## Live setup constraints

- Docker Engine is healthy. Ollama responds locally and has the installed `aura-qwen3-coding:4b-8k` model; A7 confirmed exact local selection for root and Coding Specialist. No hosted key or model download was used.
- A2 passed with live arXiv research and exact local Ollama model routing. Semantic Scholar was rate-limited during earlier checks, but the accepted workflow used reachable sources and made no hosted model calls. One later replay returned `empty_model_response`; it is recorded as a failed non-acceptance attempt, and no further retry is needed for v1.
- CodeGraph is not installed/configured and is not a v1 blocker.
- CI is deterministic and must not require paid model access, Ollama, LM Studio, or CodeGraph.
