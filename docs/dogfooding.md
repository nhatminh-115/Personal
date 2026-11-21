# AURA live dogfooding

These scripts exercise AURA API/runtime workflows beyond ordinary unit tests. Some use an isolated in-process lifespan; the project-continuity scenario starts two separate API processes. That scenario uses a deterministic mock provider, while Research and Coding require live provider setup. A green CI workflow or mock-provider report is never evidence of live inference.

## Prepare the environment

Use Python 3.12 and the repository's installed dependencies. Live model scenarios can use an OpenAI-compatible AURA route configured with:

- **MODEL_PROVIDER=openai**
- **OPENAI_API_KEY** available in the process environment

The Coding Specialist and project-memory scenarios can instead use a local
Ollama model without a cloud key. Set an exact installed model override and
keep the Ollama endpoint on loopback:

    $env:MODEL_PROVIDER = "openai"
    $env:OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
    $env:AURA_DOGFOOD_MODEL_OVERRIDE = "ollama:qwen2.5-coder:3b"
    python scripts/dogfood_coding_impact_live.py

    python scripts/dogfood_project_memory_live.py

The override is sent as an exact provider/model lock. Without a cloud key, the
harness rejects non-Ollama overrides and non-loopback Ollama URLs. It requests
`instant` reasoning for this local smoke run; when the model reports reasoning
control as unknown, AURA keeps the decision unknown and does not claim a native
provider control.

Research scenarios also require **RESEARCH_PROVIDER_MODE=live** and network access to the configured research sources. Keep credentials in environment variables or the local secret manager; do not commit them.

PowerShell example:

    $env:MODEL_PROVIDER = "openai"
    $env:RESEARCH_PROVIDER_MODE = "live"
    python scripts/dogfood_research_live.py

Run the scripts from the repository root. They use isolated SQLite databases and LangGraph checkpoints under **.aura_dogfood/**, and write run-addressable JSON reports under **artifacts/dogfood/**. Those generated files are ignored by Git.

Project continuity does not require an external model or service. Run its
process-restart acceptance check with:

    python scripts/dogfood_project_continuity.py

It starts an isolated local API process, creates a project with a linked Note,
previews and chats with only that Note selected, restarts the API process, and
checks the reopened project, transcript, and persisted context provenance. It
uses `MODEL_PROVIDER=mock` and makes no live-inference claim.

## Scenarios

| Scenario | Command | Required setup | What the report proves |
| --- | --- | --- | --- |
| Project continuity (A1) | **python scripts/dogfood_project_continuity.py** | Python 3.12 and installed repository dependencies; no external provider | **PASS on 2026-11-21** using two local API processes and `mock-default`; the linked Note, project session, selected-only context manifest, and routing/events survived a service restart. Sanitized report: [`docs/acceptance/a1-project-continuity-20261121.json`](acceptance/a1-project-continuity-20261121.json). This does not count as live inference. |
| Governed execution (A3) | **python scripts/verify_phase3.py** | Docker Desktop Linux engine and locally built `aura-coding-sandbox:latest` image | **PASS on 2026-11-21** through real Docker: three persisted approvals, initial sandbox test failed as expected, approved patch was applied, and the post-patch sandbox test passed with exit code 0. The trace confirms root/child lineage and tool results. Sanitized report: [`docs/acceptance/a3-governed-execution-20261121.json`](acceptance/a3-governed-execution-20261121.json). Uses mock inference, no live-inference claim. |
| Automation recovery (A4) | **python scripts/dogfood_automation_recovery.py** | Python 3.12 and installed repository dependencies; no external provider | **PASS on 2026-11-21**: authenticated duplicate webhook delivery reused one event; a write paused for approval, survived an API process restart, resumed with the same run and approval IDs, and completed; queued cancellation and digest-only secret storage were verified. Sanitized report: [`docs/acceptance/a4-automation-recovery-20261121.json`](acceptance/a4-automation-recovery-20261121.json). Uses mock inference and makes no live-inference claim. |
| Privacy boundary (A5) | **python scripts/dogfood_privacy_boundaries.py** | Python 3.12, installed repository dependencies, deterministic provider spies; no live provider | **PASS on 2026-11-21**: local-only/confidential cloud model, embedding, research, and capability calls were blocked before invocation. Selected file text was checkpointed but redacted from traces; a cloud route paused for durable confirmation and rejection made zero provider calls. Sanitized report: [`docs/acceptance/a5-privacy-boundary-20261121.json`](acceptance/a5-privacy-boundary-20261121.json). No live-inference claim. |
| Clean Compose backup restore (A6) | **python scripts/dogfood_compose_restore.py <backup.tar.gz> <completed-run-uuid> --api-base-url http://127.0.0.1:18000 --report docs/acceptance/a6-clean-restore-20261121.json** | Docker Desktop Linux engine; isolated `aura-a6-dogfood` Compose project with a completed mock-provider run and `aura-compose-smoke.txt`; set `AURA_DOGFOOD_ALLOW_VOLUME_RECREATE=1` | **PASS on 2026-11-21**: fresh volumes were empty before restore; run `6fa0268e-7ef1-42f8-b795-15f1983ba669`, its 10 checkpoint rows, and the workspace file were restored and verified. Sanitized report: [`docs/acceptance/a6-clean-restore-20261121.json`](acceptance/a6-clean-restore-20261121.json). Uses mock inference; no live-inference claim. |
| Research prior-art investigation | **python scripts/dogfood_research_live.py** | Hosted model credentials or an exact local Ollama override; `RESEARCH_PROVIDER_MODE=live` and network access | Root-to-Research Specialist lineage, real model selection, research tools, checkpointed state, evidence and memory counts |
| Project memory retrieval | **python scripts/dogfood_project_memory_live.py** | Hosted model credentials or an exact local Ollama override | Live run `140a579e-2e21-4709-8237-5621ebc54ec5` retrieved the target project's two-person-review/rollback rule, excluded the foreign-project decoy, printed its acceptance result, and exited 0 using the installed local Ollama model. |
| Research Context Bridge merge | **python scripts/dogfood_context_bridge_live.py** | Hosted model credentials or an exact local Ollama override; `RESEARCH_PROVIDER_MODE=live` and network access | Live run `62c9e83c-4e54-48a5-bf3a-fb2c49712d76` delegated to the Research Specialist, persisted a verified claim from extracted evidence, created a durable Context Bridge, and compiled a fresh chat with that Bridge as its only selected object. It printed acceptance and exited 0 using local Ollama. |
| Routing constraints preview | **python scripts/dogfood_routing_constraints_live.py** | Live model catalog with an available local model and a configured hosted catalog entry | Run `1e689c802120` selected `ollama:qwen2.5-coder:7b` and metadata-only `openai:gpt-4o-mini`; both adaptive draft previews preserved their exact local-only/cloud-allowed policy and made zero model calls. Local reasoning metadata stayed explicitly unknown. A catalog-only placeholder key marked the hosted entry configured; it was not sent to any provider. |
| Coding impact / CodeGraph | **python scripts/dogfood_coding_impact_live.py** | Pending external setup: CodeGraph is not installed or configured in the current environment. Do not install or download it automatically. A complete run will also need a hosted model credential or exact local Ollama override capable of delegating and using tools. | Not run. The optional CodeGraph dogfood is pending external setup and does not block other AURA milestones. |

The CodeGraph provider smoke and full Coding Specialist dogfood are pending
external setup. Do not install or download CodeGraph automatically. The
Coding Specialist, project-memory, and Context Bridge live dogfood scripts require **MODEL_PROVIDER=openai** and either
**OPENAI_API_KEY** or **AURA_DOGFOOD_MODEL_OVERRIDE=ollama:model** with
**OLLAMA_BASE_URL** on loopback. This scenario does not block other independent
AURA milestones. CodeGraph remains optional, external, and absent from CI; AURA
never installs it automatically.

The routing constraints script calls GET /v1/models, which performs its normal provider-discovery snapshot and may make local model-list HTTP requests. It does not call the explicit refresh or capability-probe endpoints, install providers, or invoke a model. The zero-invocation preview itself does not need provider credentials; a catalog-only placeholder key is sufficient to expose the configured hosted entry, and the script never sends it to the provider. The catalog must list an available explicitly classified local and hosted model; otherwise the scenario reports that it did not run.

## Approvals and audit artifacts

The research dogfood never submits a tool approval. If **/v1/chat** pauses for approval, it records the run and approval IDs in a pending JSON artifact and exits. Decide through AURA's normal approval UI, then start a new dogfood run if needed.

Reports include identifiers, route decisions, tool names, statuses, counts, and safe context manifests. They do not include prompts, source excerpts, memory text, or model responses. Treat the isolated database and checkpoint files as run evidence; a later run will not delete them.

The Coding Specialist dogfood also writes a sanitized report when `/v1/chat`
returns a non-200 response, provided the failed run was persisted. The report
uses the run ID recovered from its isolated session and records the HTTP status
and safe persisted events; it does not copy the response body or exception text.

## Interpreting results

A script prints **ACCEPTANCE RESULT** only when its own live acceptance checks pass. A preflight message or exit code 2 means that scenario did not run or is paused; it is not a pass. A CI pass verifies deterministic behavior only. Cross-session project-memory dogfood has been verified locally with an explicit loopback Ollama override. CodeGraph dogfood remains pending external setup and a capable model; no current-environment provider smoke is claimed.

For A1, the committed report under `docs/acceptance/` is the durable sanitized
record. Its `mock` route proves persistence and scope only; O7 and A7 still
require a representative workflow with a real configured provider.
