# AURA Autonomous Continuation

Updated: 2026-10-05

## Goal

Continue turning AURA into a durable personal AI workspace/runtime: one root orchestrator, restartable runs, explicit routing and permissions, safe tool execution, and traceable outcomes. Work on the highest-value reliability or product gap that can be completed without waiting on external setup. Continue through green milestones while quota allows.

## Current repository state

- Canonical `main`: `ef5578f6173f2f51c4d3972029e3938101cd26b3`.
- PRs [#336](https://github.com/nhatminh-115/Personal/pull/336), [#337](https://github.com/nhatminh-115/Personal/pull/337), [#338](https://github.com/nhatminh-115/Personal/pull/338), [#339](https://github.com/nhatminh-115/Personal/pull/339), [#340](https://github.com/nhatminh-115/Personal/pull/340), [#341](https://github.com/nhatminh-115/Personal/pull/341), [#342](https://github.com/nhatminh-115/Personal/pull/342), [#343](https://github.com/nhatminh-115/Personal/pull/343), [#344](https://github.com/nhatminh-115/Personal/pull/344), [#345](https://github.com/nhatminh-115/Personal/pull/345), and [#346](https://github.com/nhatminh-115/Personal/pull/346) are merged.
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
- PR #345 fixed parent cancellation leaving delegated child runs and approval links waiting. It merged as `e6d7001b5f2a03a0c705f456c35bd372de21a80b`. Final CI run #903 (`37341654963`), job `111869946318`, passed: backend 680 tests in 52.58s; Phases 1/2.1/3/4 passed; frontend 47 files / 318 tests; Vite build 9.24s. CI #902 found one repeated-decision status-code compatibility regression (400 expected); it was corrected and the full CI rerun passed.
- PR #346 serialized cancellation requests with run resumes and prevented approval/routing-confirmation resumes after cancellation is acknowledged. It merged as `ef5578f6173f2f51c4d3972029e3938101cd26b3`. Final CI run #907 (`37344410275`), job `111879258794`, passed: backend 680 tests in 77.91s; Phases 1/2.1/3/4 passed; frontend 47 files / 318 tests; Vite build 12.08s. Earlier CI attempts exposed a test variable typo and a repeatable test-hook wait; both were fixed before the green run.
- Active branch: `codex/aura-next-milestone-20261005-104`, created from the canonical SHA above.
- Completed on PR #341: sanitized Research provider/cache/PDF diagnostics in logs, returned errors, and exception chains, while preserving useful HTTP and destination categories.
- Completed on PR #342: sanitized MCP runtime/config errors and validation failures, preserving safe categories and server crash isolation.
- Completed on PR #343: preserve failed/cancelled Research child status when partial `research_state` exists while retaining partial artifacts and errors.
- Completed on PR #344: an approved delegated child failing during graph resume now persists the child/delegation terminal state, clears stale approval linkage, and resumes the matching root interrupt with the failure result.
- Completed on PR #345: cancellation during root finalization now marks active descendant runs and delegations cancelled, records child cancellation events, and prevents matching approval/routing-confirmation retries from resuming terminal runs.
- Completed on PR #346: cancellation now holds the root and existing child resume locks before persisting `cancel_requested_at`; approval and routing-confirmation endpoints reject resume attempts after cancellation is acknowledged.
- Current milestone (branch 104): make cancellation-requested chat turns recoverable when their in-flight executor exits before finalization. An active executor owns a per-run execution lock; a repeated stop or idempotent chat retry finalizes the persisted request only after it can claim that lock. A deterministic integration regression simulates a lost executor. Local pytest is unavailable because the active Python environment lacks `aiosqlite` and `pytest`; static parse and diff checks pass. Remote CI verification is pending.

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
| PR #345: cancel delegated child runs with parent turn | Merged as `e6d7001`; CI #903 (`37341654963`), backend 680 passed in 52.58s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 9.24s |
| PR #346: serialize cancellation and run resume | Merged as `ef5578f`; CI #907 (`37344410275`), backend 680 passed in 77.91s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 12.08s |

## Immediate next steps

1. Check the recovery lock/finalization paths for regression risks and confirm the lost-executor integration test shape.
2. Commit this milestone to branch 104, push it, and open a PR.
3. Wait for GitHub Actions; merge only when all required checks are green.
4. Start the next highest-value non-blocked root/child durability audit while quota allows; CodeGraph setup remains pending external setup and is not a blocker.

## Dogfood and external setup

- CodeGraph installation and CodeGraph dogfood remain pending external setup. Do not install or download CodeGraph automatically. This does not block other AURA work.
- Local model dogfood is not a code-completion gate. Recent local Ollama calls have stopped or exceeded available hardware for some scenarios. Do not silently route to a hosted model.
- Crossref is AURA Research's scholarly metadata source: it can help look up DOI, title, author, and publication records for citation/provenance checks. It does not provide a general full-text paper download service.

## Verification constraints

- This worktree does not have `pytest` installed. Python AST parsing and `git diff --check` run locally; GitHub Actions runs the backend suite and integration scenarios.
- No paid/hosted model is required for CI.
- Keep changes isolated on a fresh branch from canonical `main`, then report exact merge SHA and remote CI evidence.
