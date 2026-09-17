# ADR-005: Isolated Execution Sandbox and Workspace Boundaries

## Status
Accepted

## Context
Tools executed by personal AI agents have the potential to read sensitive host credentials (such as `~/.ssh`, `~/.aws`, system registry) or overwrite critical operating system files if not strictly bounded.

In addition, future tool features (such as arbitrary Python or Bash code execution) present arbitrary remote code execution (RCE) vectors on the host machine.

## Decision
We establish a two-phase isolation sandbox architecture:

### 1. Phase 1: Workspace Sandbox Boundary (Filesystem Jail)
- All filesystem-based tools (`list_workspace_files`, `read_workspace_file`, `write_workspace_file`) are constrained to a single configured root directory: `AURA_WORKSPACE_ROOT`.
- Path resolution is enforced through `app.sandbox.workspace.resolve_workspace_path`:
  - Input relative or absolute paths are canonicalized using `Path.resolve()`.
  - The canonical path must be verified to start strictly with the canonical `AURA_WORKSPACE_ROOT`.
  - Any traversal attempt (e.g., `../../etc/passwd`, `C:\Windows\System32`, symlink escapes) raises a fatal `WorkspaceEscapeError` (`ACCESS DENIED`).

### 2. Phase 2: Isolated Container Sandbox (Shell & Code Execution)
- Arbitrary shell commands (`shell.execute`) or script evaluations will not be run on the host machine.
- They will be routed to a containerized sandbox runtime (Docker / gVisor) with:
  - Read-only root filesystem.
  - Ephemeral mounted workspace volume.
  - Disabled network access by default.
  - CPU, memory, and execution time limits.
- Phase 1 defines the `SandboxExecutor` interface and postpones un-sandboxed shell execution on the host to eliminate any compromise of host security.

## Consequences
### Positive
- Prevents malicious or hallucinated file reads and writes from escaping the designated workspace.
- Host machine security is uncompromised during development and demo phases.
- Clear path for plugging in full Docker-based code execution in Phase 2.

### Negative / Trade-offs
- The agent cannot directly edit files outside the configured workspace without administrative reconfiguration.
