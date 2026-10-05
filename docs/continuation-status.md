# AURA Autonomous Continuation

Updated: 2026-10-05

## Goal

Continue turning AURA into a durable personal AI workspace/runtime: one root orchestrator, restartable runs, explicit routing and permissions, safe tool execution, and traceable outcomes. Work on the highest-value reliability or product gap that can be completed without waiting on external setup. Continue through green milestones while quota allows.

## Current repository state

- Canonical `main`: `c3c18d480a3a6f72891d058cf0c2cf9adc89d953`.
- PR [#336](https://github.com/nhatminh-115/Personal/pull/336) and PR [#337](https://github.com/nhatminh-115/Personal/pull/337) are merged.
- PR #337 closes the provider-error leak when an approved specialist finishes but the root orchestrator fails while resuming. It stores safe root-run text and a `provider_failure` trace category.
- PR #337 CI run #880 (`37326069933`) passed: backend 665 tests, Phases 1/2.1/3/4, frontend 47 test files, Vite build 12.42s.
- Active branch: `codex/aura-next-milestone-20261005-95`, created from the canonical SHA above.
- Current change: preserve the previous behavior for non-provider parent-resume failures; only typed provider failures receive safe persisted user-facing text and the provider failure trace category.

## Recent verified milestones

| Change | Result |
| --- | --- |
| PR #334: restore cancellation state after reloading live chat | Merged; CI #872, backend 662 passed, Phases 1/2.1/3/4 passed, frontend 47 files / 317 tests, Vite build 12.14s |
| PR #335: classify and redact provider errors in `/v1/chat` | Merged; CI #874, backend 663 passed, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 12.25s |
| PR #336: redact provider errors on approval and routing-confirmation resume, including specialist child failures | Merged; CI #877, backend 664 passed in 80.38s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 11.92s |
| PR #337: redact provider errors when resuming the parent run after specialist approval | Merged; CI #880, backend 665 passed in 80.17s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 12.42s |

## Immediate next steps

1. Finish the current regression check so generic parent-resume exceptions are not newly persisted to the database.
2. Open a small PR, wait for GitHub Actions, and merge only after all required checks are green.
3. Continue the runtime reliability audit. Prioritize failures that can leave the user's root run, delegated specialist, approval, cancellation, or persisted result in contradictory states. Add deterministic regression coverage and use remote CI as the completion gate.
4. Repeat the audit and implementation cycle while quota allows; do not start a blocked external dogfood task as if it were a code milestone.

## Dogfood and external setup

- CodeGraph installation and CodeGraph dogfood remain pending external setup. Do not install or download CodeGraph automatically. This does not block other AURA work.
- Local model dogfood is not a code-completion gate. Recent local Ollama calls have stopped or exceeded available hardware for some scenarios. Do not silently route to a hosted model.
- Crossref is AURA Research's scholarly metadata source: it can help look up DOI, title, author, and publication records for citation/provenance checks. It does not provide a general full-text paper download service.

## Verification constraints

- This worktree does not have `pytest` installed. Python compile checks and focused smoke checks run locally; GitHub Actions runs the backend suite and integration scenarios.
- No paid/hosted model is required for CI.
- Keep changes isolated on a fresh branch from canonical `main`, then report exact merge SHA and remote CI evidence.
