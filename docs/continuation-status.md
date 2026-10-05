# AURA Autonomous Continuation

Updated: 2026-10-05

## Goal

Continue turning AURA into a durable personal AI workspace/runtime: one root orchestrator, restartable runs, explicit routing and permissions, safe tool execution, and traceable outcomes. Work on the highest-value reliability or product gap that can be completed without waiting on external setup. Continue through green milestones while quota allows.

## Current repository state

- Canonical `main`: `3305a0235ee7405e68331ac01b7a8fe9a5a321e8`.
- PRs [#336](https://github.com/nhatminh-115/Personal/pull/336), [#337](https://github.com/nhatminh-115/Personal/pull/337), [#338](https://github.com/nhatminh-115/Personal/pull/338), [#339](https://github.com/nhatminh-115/Personal/pull/339), and [#340](https://github.com/nhatminh-115/Personal/pull/340) are merged.
- PR #337 closes the provider-error leak when an approved specialist finishes but the root orchestrator fails while resuming. It stores safe root-run text and a `provider_failure` trace category.
- PR #337 CI run #880 (`37326069933`) passed: backend 665 tests, Phases 1/2.1/3/4, frontend 47 test files, Vite build 12.42s.
- PR [#338](https://github.com/nhatminh-115/Personal/pull/338) is merged. It preserves prior behavior for non-provider parent-resume failures.
- PR #338 CI run #882 (`37327320311`) passed: backend 666 tests in 61.14s, Phases 1/2.1/3/4, frontend 47 test files, Vite build 9.58s.
- PR #339 CI run #884 (`37328473820`) passed: backend 667 tests in 74.91s, Phases 1/2.1/3/4, frontend 47 test files, Vite build 11.59s.
- PR #340 CI run #887 (`37329744878`) passed: backend 669 tests in 77.60s, Phases 1/2.1/3/4, frontend 47 test files, Vite build 11.80s.
- PR [#341](https://github.com/nhatminh-115/Personal/pull/341) is open with all checks green; CI run #892 (`37332648298`) passed.
- Active branch: `codex/aura-next-milestone-20261005-98`, created from the canonical SHA above.
- Completed on PR #341: sanitized Research provider/cache/PDF diagnostics in logs, returned errors, and exception chains, while preserving useful HTTP and destination categories. Remote backend and frontend suites pass.
- Next audit after #341 merges: inspect MCP and remaining external capability failure paths for raw provider errors, sensitive request details, and resumable-run state inconsistencies.

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
| PR #341: redact Research provider, cache, and PDF diagnostics | Open; CI #892 (`37332648298`), backend 671 passed in 71.48s, Phases 1/2.1/3/4 passed, frontend 47 files / 318 tests, Vite build 8.44s |

## Immediate next steps

1. Merge PR #341 after confirming its final CI run metadata.
2. Create a fresh branch from canonical `main` and audit MCP/external capability error and resume paths.
3. Continue the runtime reliability and privacy audit, fixing the next reproducible issue with deterministic coverage.
4. Repeat the audit and implementation cycle while quota allows; do not start a blocked external dogfood task as if it were a code milestone.

## Dogfood and external setup

- CodeGraph installation and CodeGraph dogfood remain pending external setup. Do not install or download CodeGraph automatically. This does not block other AURA work.
- Local model dogfood is not a code-completion gate. Recent local Ollama calls have stopped or exceeded available hardware for some scenarios. Do not silently route to a hosted model.
- Crossref is AURA Research's scholarly metadata source: it can help look up DOI, title, author, and publication records for citation/provenance checks. It does not provide a general full-text paper download service.

## Verification constraints

- This worktree does not have `pytest` installed. Python AST parsing and `git diff --check` run locally; GitHub Actions runs the backend suite and integration scenarios.
- No paid/hosted model is required for CI.
- Keep changes isolated on a fresh branch from canonical `main`, then report exact merge SHA and remote CI evidence.
