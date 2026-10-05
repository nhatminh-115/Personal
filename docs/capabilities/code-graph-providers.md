# Optional code graph providers

AURA treats code intelligence as an optional capability provider. The Coding
Specialist always retains its native workspace and sandbox tools; configured
providers add tools only after MCP discovery confirms that the declared tools
exist. Missing providers do not block coding delegation, and AURA does not
install or bundle a provider.

## Capability contract

Coding requests these optional capabilities:

| Capability | Intended use |
| --- | --- |
| `code_graph.context` | Build a compact overview of relevant code |
| `code_graph.query` | Search symbols and relationships |
| `code_graph.impact` | Trace callers, dependencies, and change impact |
| `code_graph.trace` | Follow a call or dependency path |

Map only tools that the chosen provider actually exposes. AURA's MCP config
uses `capabilities_by_tool` to make this mapping explicit. Provider metadata is
not used to infer capabilities from a server name. Unavailable or undiscovered
providers contribute no tools, while required capabilities continue to fail
closed. Tool risk, permission, and approval policy is still enforced by AURA.

## Dogfood status

CodeGraph 0.20.1 is installed with telemetry disabled in the maintainer's
Windows environment. In live run
`98637894-40c8-4df0-b040-11eaadc24e00`, AURA delegated to the Coding
Specialist, which called the discovered read-only
`mcp_codegraph_codegraph_symbol_search` tool. The sanitized report records the
local `ollama:aura-qwen3-coding:4b-8k` route, completed parent and child runs,
present checkpoints, and no pending approvals or tool failures. The dogfood
printed its acceptance result and exited 0. This verifies the optional provider
through a live AURA run. It remains external and is not a CI dependency; AURA
does not install it automatically.

## Candidate review

The candidate review is a fit check for an optional MCP boundary, not a claim
that any provider has been installed or exercised against a live AURA run.

| Candidate | Current integration fit | License / operational note |
| --- | --- | --- |
| [CodeGraph](https://github.com/codegraph-ai/CodeGraph) | Best first dogfood candidate: documents an MCP server, a graph-focused tool profile, and broad language support. | README states Apache-2.0. It uses a native analysis engine and may download it during install. Upstream says anonymous usage telemetry is enabled by default and documents `CODEGRAPH_TELEMETRY=off`; the example opts out. |
| [GitNexus](https://github.com/abhigyanpatwari/GitNexus) | Strong local CLI/MCP candidate with context, query, and impact functions. | Current repository license is PolyForm Noncommercial 1.0.0. Keep it external and do not bundle, copy, or distribute its code or binary; use may require a separate commercial license depending on purpose. |
| [rgctl (formerly rBuilder)](https://github.com/sshaaf/rgctl) | Strong reachability, blast-radius, slicing, and taint-analysis CLI. Its current README presents CLI/HTTP usage, so it would need an adapter before fitting AURA's current MCP lifecycle. | README states MIT. |
| [GraphRepo](https://github.com/the-muses-ltd/GraphRepo) | Local MCP with graph traversal and semantic search, plus a VS Code surface. | README states MIT and supports a narrower listed language set; repository maturity should be evaluated through dogfood before adoption. |

The first optional provider experiment should use CodeGraph through the existing
MCP configuration and explicitly mapped read-only tools. AURA should keep the
provider external. Do not copy its server, download its binary automatically,
or make it a CI dependency. Recheck upstream license, tool names, platform
support, and network behavior before each real installation or distribution.

## Example MCP configuration

Install and configure a provider separately, then add its executable and
workspace path to the user's MCP configuration. CodeGraph's current MCP
package documents `codegraph-mcp` as its stdio command and prefixes exposed
tool names with `codegraph_`. Verify the installed release's `tools/list`
response before enabling the mappings below; upstream command names can change.

```yaml
servers:
  - id: codegraph
    name: CodeGraph
    transport: stdio
    command: codegraph-mcp
    args: ["--profile=all"]
    cwd: <absolute-workspace-path>
    env:
      CODEGRAPH_TELEMETRY: "off"
    enabled: true
    read_only: true
    allowed_tools:
      - codegraph_symbol_search
      - codegraph_get_ai_context
      - codegraph_get_edit_context
      - codegraph_analyze_impact
      - codegraph_get_callers
      - codegraph_get_callees
      - codegraph_get_call_graph
      - codegraph_get_dependency_graph
      - codegraph_traverse_graph
    capabilities_by_tool:
      codegraph_symbol_search: [code_graph.query]
      codegraph_get_ai_context: [code_graph.context]
      codegraph_get_edit_context: [code_graph.context]
      codegraph_analyze_impact: [code_graph.impact]
      codegraph_get_callers: [code_graph.trace]
      codegraph_get_callees: [code_graph.trace]
      codegraph_get_call_graph: [code_graph.trace]
      codegraph_get_dependency_graph: [code_graph.trace]
      codegraph_traverse_graph: [code_graph.trace]
    privacy_boundary: local
    network_requirement: unknown
    data_touched: [repository_source, code_index]
    permissions: [read]
    approval_requirement: per_tool_policy
```

The sample allowlist contains only upstream-documented read-oriented tools.
Remove any name not present in the installed server's discovery result; add a
mapping only when the corresponding tool has been reviewed. Keep
mutating/index-management tools outside the Coding Specialist scope unless a
separate reviewed need emerges. `read_only` controls AURA's MCP policy overlay;
it does not independently prove that an upstream server operation is safe.
The telemetry opt-out follows the [upstream MCP package configuration](https://github.com/codegraph-ai/CodeGraph/blob/main/mcp-package/README.md#telemetry).

## Verification boundary

CI verifies registry and specialist scoping with deterministic local fixtures.
It does not install CodeGraph or assert live provider health. A real dogfood
run must record the AURA run ID, discovered provider/tool metadata, project
scope, selected code graph tools, result artifact, and any failures before the
provider can be described as verified.
