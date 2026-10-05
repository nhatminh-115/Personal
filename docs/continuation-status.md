# AURA Autonomous Continuation

Updated: 2026-10-05

## Goal

Continue turning AURA into a durable personal AI workspace/runtime: one root orchestrator, restartable runs, explicit routing and permissions, safe tool execution, and traceable outcomes. Work on the highest-value reliability or product gap that can be completed without waiting on external setup. Continue through green milestones while quota allows.

## Current repository state

- Canonical `main`: `b8c7ed5f65c69763e4f30b8c7eb0d87cf64c4f37`.
- PRs [#336](https://github.com/nhatminh-115/Personal/pull/336), [#337](https://github.com/nhatminh-115/Personal/pull/337), [#338](https://github.com/nhatminh-115/Personal/pull/338), [#339](https://github.com/nhatminh-115/Personal/pull/339), [#340](https://github.com/nhatminh-115/Personal/pull/340), [#341](https://github.com/nhatminh-115/Personal/pull/341), [#342](https://github.com/nhatminh-115/Personal/pull/342), [#343](https://github.com/nhatminh-115/Personal/pull/343), and [#344](https://github.com/nhatminh-115/Personal/pull/344) are merged.
- PR #337 closes the provider-error leak when an approved specialist finishes but the root orchestrator fails while resuming. It stores safe root-run text and a `provider_failure` trace category.
- PR #337 CI run #880 (`37326069933`) passed: backend 665 tests, Phases 1/2.1/3/4, frontend 47 test files, Vite build 12.42s.
- PR [#338](https://github.com/nhatminh-115/Personal/pull/338) is merged. It preserves prior behavior for non-provider parent-resume failures.
- PR #338 CI run #882 (`37327320311`) passed: backend 666 tests in 61.14s, Phases 1/2.1/3/4, frontend 47 test files, Vite build 9.58s.
- PR #339 CI run #884 (`37328473820`) passed: backend 667 tests in 74.91s, Phases 1/2.1/3/4, frontend 47 test files, Vite build 11.59s.
- PR #340 CI run #887 (`37329744878`) passed: backend 669 tests in 77.60s, Phases 1/2.1/3/4, frontend 47 test files, Vite build 11.80s.
- PR #341 merged as `c8de2ba644bd99b1d880900f8e8fae6a9b3caa46`. Final CI run #893 (`37333526794`) passed: backend 671 tests in 80.59s, Phases 1/2.1/3/4, frontend 47 test files / 318 tests, Vite build 12.34s.
- PR #342 merged as `930864a44bc75aac246890a18963d18855cf0107`. Final CI run #896 (`37336141268`) passed: backend 676 tests in 81.54s, Phases 1/2.1/3/4, frontend 47 test files / 318 tests, Vite build 12.10s.
- PR #343 fixed Research delegation synthesis overwriting terminal child status when partial research state exists. It merged as `36ae0198e73f651eba8fcbefa5f573f8bd8177ec`. CI run #898 (`37337627934`), job `111856307701`, passed: backend 678 tests in 81.32s; Phases 1/2.1/3/4 passed; frontend 47 files / 318 tests; Vite build 12.15s.
- PR #344 fixed delegated child resume failures leaving the delegation/root lifecycle unresolved. It merged as `b8c7ed5f65c69763e4f30b8c7eb0d87cf64c4f37`. CI run #900 (`37339311176`), job `111862023469`, passed: backend 679 tests in 79.60s; Phases 1/2.1/3/4 passed; frontend 47 files / 318 tests; Vite build 11.93s.
- Active branch: `codex/aura-next-milestone-20261005-102`, created from the canonical SHA above.
- Completed on PR #341: sanitized Research provider/cache/PDF diagnostics in logs, returned errors, and exception chains, while preserving useful HTTP and destination categories.
- Completed on PR #342: sanitized MCP runtime/config errors and validation failures, preserving safe categories and server crash isolation.
- Completed on PR #343: preserve failed/cancelled Research child status when partial `research_state` exists while retaining partial artifacts and errors.
- Completed on PR #344: an approved delegated child failing during graph resume now persists the child/delegation terminal state, clears stale approval linkage, and resumes the matching root interrupt with the failure result.
- Current milestone (branch 102): cancellation can win after a delegated specialist has paused for approval but before the root chat response finalizes. Closing the pending approval alone leaves the child run and delegation in `waiting_for_approval`; cancellation finalization now marks active descendants and their delegation records cancelled, records child cancellation events, and prevents a retry from resuming a terminal child graph. Regression coverage pauses the root at the cancellation race and verifies root/child/delegation/approval state plus retry behavior; CI verification is pending.

## Recent verified milestones

| Change | Result |
| --- | --- |
| PR #334: restore cancellation state after reloading live chat | Merged; CI #872, backend 662 passed, Phases 1/2.1/3/4 passed, frontend 47 files / 317 tests, Vite build 12.14s |
| PR #335: classify and redact provider errors in `/v1/chat` | Merged; CI #874, backend 663 passed, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 12.25s |
| PR #336: redact provider errors on approval and routing-confirmation resume, including specialist child failures | Merged; CI #877, backend 664 passed in 80.38s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 11.92s |
| PR #337: redact provider errors when resuming the parent run after specialist approval | Merged; CI #880, backend 665 passed in 80.17s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 12.42s |
| PR #338: preserve non-provider parent-resume error behavior | Merged; CI #882, backend 666 passed in 61.14s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 9.58s |
| PR #339: redact OpenAI-compatible model transport diagnostics | Merged; CI #884, backend 667 passed in 74.91s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 11.59s |
| PR #340: redact embedding provider HTTP and transport errors | Merged; CI #887, backend 669 passed in 77.60s, Phases 1/2.1/3/4 passed, frontend 47 files / all tests passed, Vite build 11.80s |
| PR #341: redact Research provider, cache, and PDF diagnostics | Merged as `c8de2ba`; CI #893 (`37333526794`), backend 671 passed in 80.59s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 12.34s |
| PR #342: redact MCP operational diagnostics | Merged as `930864a`; CI #896 (`37336141268`), backend 676 passed in 81.54s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 12.10s |
| PR #343: preserve terminal Research child run status when partial state exists | Merged as `36ae019`; CI #898 (`37337627934`), backend 678 passed in 81.32s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 12.15s |
| PR #344: propagate delegated child resume failures | Merged as `b8c7ed5`; CI #900 (`37339311176`), backend 679 passed in 79.60s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 11.93s |

## Immediate next steps

1. Verify the delegated-child cancellation race and terminal approval retry regression in CI.
2. Open a PR, wait for GitHub Actions, and merge only after all required checks are green.
3. Continue auditing root/child persistence and resume paths for the next independently verifiable reliability gap.
4. Repeat while quota allows; CodeGraph setup remains pending external setup and is not a blocker.
4. Repeat the audit and implementation cycle while quota allows; do not start a blocked external dogfood task as if it were a code milestone.

## Dogfood and external setup

- CodeGraph installation and CodeGraph dogfood remain pending external setup. Do not install or download CodeGraph automatically. This does not block other AURA work.
- Local model dogfood is not a code-completion gate. Recent local Ollama calls have stopped or exceeded available hardware for some scenarios. Do not silently route to a hosted model.
- Crossref is AURA Research's scholarly metadata source: it can help look up DOI, title, author, and publication records for citation/provenance checks. It does not provide a general full-text paper download service.

## Verification constraints

- This worktree does not have `pytest` installed. Python AST parsing and `git diff --check` run locally; GitHub Actions runs the backend suite and integration scenarios.
- No paid/hosted model is required for CI.
- Keep changes isolated on a fresh branch from canonical `main`, then report exact merge SHA and remote CI evidence.
