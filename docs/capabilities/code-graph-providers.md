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

## Candidate review

The candidate review is a fit check for an optional MCP boundary, not a claim
that any provider has been installed or exercised against a live AURA run.

| Candidate | Current integration fit | License / operational note |
| --- | --- | --- |
| [CodeGraph](https://github.com/codegraph-ai/CodeGraph) | Best first dogfood candidate: documents an MCP server, a graph-focused tool profile, and broad language support. | README states Apache-2.0. It uses a native analysis engine and may offer a user-controlled first-run download; keep setup opt-in and network metadata unknown until verified for the selected installation. |
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
workspace path to the user's MCP configuration. The following is a shape
example only; confirm tool names against the installed provider's
`tools/list` response before declaring mappings:

```yaml
servers:
  - id: codegraph
    name: CodeGraph
    transport: stdio
    command: codegraph-server
    args: ["--mcp", "--profile=graph"]
    cwd: <absolute-workspace-path>
    enabled: true
    read_only: true
    allowed_tools: [] # Replace with explicitly reviewed discovered tool names.
    capabilities_by_tool: {}
    privacy_boundary: local
    network_requirement: unknown
    data_touched: [repository_source, code_index]
    permissions: [read]
    approval_requirement: per_tool_policy
```

An empty allowlist is intentionally not a useful live configuration. After
reviewing the discovered tool list, add only read-only query/context/impact
tools and map each name to the corresponding `code_graph.*` capability. Keep
mutating/index-management tools outside the Coding Specialist scope unless a
separate reviewed need emerges. `read_only` controls AURA's MCP policy overlay;
it does not independently prove that an upstream server operation is safe.

## Verification boundary

CI verifies registry and specialist scoping with deterministic local fixtures.
It does not install CodeGraph or assert live provider health. A real dogfood
run must record the AURA run ID, discovered provider/tool metadata, project
scope, selected code graph tools, result artifact, and any failures before the
provider can be described as verified.
