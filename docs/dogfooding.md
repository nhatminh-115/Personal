# AURA live dogfooding

These scripts exercise the real AURA API/runtime outside deterministic CI. CI tests the harness helpers; a green workflow does not mean a live provider run occurred.

## Prepare the environment

Use Python 3.12 and the repository's installed dependencies. Live model scenarios require an OpenAI-compatible AURA route configured with:

- **MODEL_PROVIDER=openai**
- **OPENAI_API_KEY** available in the process environment

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
| Project memory retrieval | **python scripts/dogfood_project_memory_live.py** | Live model | A fresh session retrieves the expected project memory and does not retrieve a conflicting fact from another project |
| Research Context Bridge merge | **python scripts/dogfood_context_bridge_live.py** | Live model and research providers | A Research Specialist claim and evidence are persisted, selected into a durable Context Bridge, then compiled into a new chat as the sole selected object |
| Routing constraints preview | **python scripts/dogfood_routing_constraints_live.py** | Live model catalog with an available local model and hosted model | Exact catalog models preserve local-only and cloud-allowed profile policies through zero-invocation routing preview |
| Coding impact / CodeGraph | **python scripts/dogfood_coding_impact_live.py** | External CodeGraph setup required for CodeGraph-specific dogfood | **Pending external setup.** Do not run or claim CodeGraph dogfood until CodeGraph is installed and its provider is discovered. The harness never installs or configures it. |

The routing constraints script calls GET /v1/models, which performs its normal provider-discovery snapshot and may make local model-list HTTP requests. It does not call the explicit refresh or capability-probe endpoints, install providers, or invoke a model. The zero-invocation preview itself does not require model credentials. The catalog must list an available explicitly classified local and hosted model; otherwise the scenario reports that it did not run.

## Approvals and audit artifacts

The research dogfood never submits a tool approval. If **/v1/chat** pauses for approval, it records the run and approval IDs in a pending JSON artifact and exits. Decide through AURA's normal approval UI, then start a new dogfood run if needed.

Reports include identifiers, route decisions, tool names, statuses, counts, and safe context manifests. They do not include prompts, source excerpts, memory text, or model responses. Treat the isolated database and checkpoint files as run evidence; a later run will not delete them.

## Interpreting results

A script prints **ACCEPTANCE RESULT** only when its own live acceptance checks pass. A preflight message or exit code 2 means that scenario did not run or is paused; it is not a pass. A CI pass verifies deterministic behavior only. CodeGraph-specific dogfood remains pending until external setup is complete.
