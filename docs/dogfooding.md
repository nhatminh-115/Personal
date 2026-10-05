# AURA live dogfooding

These scripts exercise the real AURA API/runtime outside deterministic CI. CI tests the harness helpers; a green workflow does not mean a live provider run occurred.

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

## Scenarios

| Scenario | Command | Required setup | What the report proves |
| --- | --- | --- | --- |
| Research prior-art investigation | **python scripts/dogfood_research_live.py** | Live model and research providers | Root-to-Research Specialist lineage, real model selection, research tools, checkpointed state, evidence and memory counts |
| Project memory retrieval | **python scripts/dogfood_project_memory_live.py** | Hosted model credentials or an exact local Ollama override | A fresh session retrieves the expected project memory and does not retrieve a conflicting fact from another project |
| Research Context Bridge merge | **python scripts/dogfood_context_bridge_live.py** | Live model and research providers | A Research Specialist claim and evidence are persisted, selected into a durable Context Bridge, then compiled into a new chat as the sole selected object |
| Routing constraints preview | **python scripts/dogfood_routing_constraints_live.py** | Live model catalog with an available local model and hosted model | Exact catalog models preserve local-only and cloud-allowed profile policies through zero-invocation routing preview |
| Coding impact / CodeGraph | **python scripts/dogfood_coding_impact_live.py** | Hosted model credentials or an exact local Ollama override; CodeGraph is optional | Live run `98637894-40c8-4df0-b040-11eaadc24e00` delegated to the Coding Specialist, used the discovered `mcp_codegraph_codegraph_symbol_search` tool, selected the installed local `ollama:aura-qwen3-coding:4b-8k` model, and completed with parent and child checkpoints present and no pending approvals or tool failures. The script printed its acceptance result and exited 0. |

The provider smoke test verifies MCP health, discovery, and one read-only tool
call; it is not a complete AURA Coding Specialist run. The Coding Specialist
and project-memory live dogfood scripts require **MODEL_PROVIDER=openai** and either
**OPENAI_API_KEY** or **AURA_DOGFOOD_MODEL_OVERRIDE=ollama:model** with
**OLLAMA_BASE_URL** on loopback. This scenario does not block other independent
AURA milestones. CodeGraph remains optional, external, and absent from CI; AURA
never installs it automatically.

The routing constraints script calls GET /v1/models, which performs its normal provider-discovery snapshot and may make local model-list HTTP requests. It does not call the explicit refresh or capability-probe endpoints, install providers, or invoke a model. The zero-invocation preview itself does not require model credentials. The catalog must list an available explicitly classified local and hosted model; otherwise the scenario reports that it did not run.

## Approvals and audit artifacts

The research dogfood never submits a tool approval. If **/v1/chat** pauses for approval, it records the run and approval IDs in a pending JSON artifact and exits. Decide through AURA's normal approval UI, then start a new dogfood run if needed.

Reports include identifiers, route decisions, tool names, statuses, counts, and safe context manifests. They do not include prompts, source excerpts, memory text, or model responses. Treat the isolated database and checkpoint files as run evidence; a later run will not delete them.

The Coding Specialist dogfood also writes a sanitized report when `/v1/chat`
returns a non-200 response, provided the failed run was persisted. The report
uses the run ID recovered from its isolated session and records the HTTP status
and safe persisted events; it does not copy the response body or exception text.

## Interpreting results

A script prints **ACCEPTANCE RESULT** only when its own live acceptance checks pass. A preflight message or exit code 2 means that scenario did not run or is paused; it is not a pass. A CI pass verifies deterministic behavior only. CodeGraph provider smoke and the read-only Coding Specialist dogfood have both been verified locally; the dogfood used an explicit loopback Ollama override and did not require hosted credentials.
