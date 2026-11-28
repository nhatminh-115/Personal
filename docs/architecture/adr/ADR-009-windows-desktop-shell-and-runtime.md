# ADR-009: Windows Desktop Shell and Managed Runtime

## Status

Accepted

## Context

Kuractus's production UI is React/Vite and its local full-featured data layer uses
PostgreSQL with pgvector, LangGraph checkpoints, workspace files, and the
existing Docker sandbox runtime. A desktop release must run outside the source
checkout, keep data durable, preserve the sandbox boundary, and expose native
Windows behavior without creating another orchestrator.

Two shell options were considered:

- **Tauri 2:** embeds the installed Windows WebView2 runtime, calls a small set
  of Rust commands, and supports per-window/plugin capabilities.
- **Electron:** bundles Chromium and Node.js and offers a mature desktop API,
  but its renderer-to-main-process bridge must be maintained as a separate
  privileged IPC surface.

Two backend packaging options were considered:

- **Full Compose runtime:** package a Compose definition for the API,
  PostgreSQL, and workspace/checkpoint storage. The API container would need
  Docker daemon access to keep Kuractus's current sandbox execution available.
- **Packaged Python sidecar:** ship the existing FastAPI/LangGraph runtime as
  a Windows executable and manage PostgreSQL/pgvector through a small Compose
  project. The API runs as the desktop user's child process and uses the
  existing Docker SDK sandbox implementation directly.

## Decision

Use **Tauri 2 + the existing React/Vite frontend**. Use narrowly scoped Rust
commands for runtime lifecycle, OS settings, and file access; do not register a
frontend shell/process plugin or expose arbitrary command execution.

Package the existing API as a Windows sidecar and manage only PostgreSQL with
Docker Compose. This keeps the database on PostgreSQL/pgvector and lets the
current DockerSandboxRuntime apply its existing container restrictions without
mounting the Docker socket into an API container. The Postgres image is pinned
by version and manifest digest. The desktop process starts the sidecar with
loopback binding, a generated API token, AppData checkpoint/workspace paths,
and the configured provider settings. Docker Desktop is a stated runtime
prerequisite; Kuractus does not install or bundle Docker Engine.

The sidecar lifecycle is owned by one Rust runtime manager. It starts the
Postgres Compose service, waits for database health, applies Alembic migrations,
starts the sidecar, waits for `/ready`, and records actionable failures. Normal
stop uses `docker compose stop`; no runtime command removes volumes. The API
token and database password are generated once and stored with the Windows
credential manager. The app passes them only to the local child processes.

## Consequences

### Positive

- Existing React product surfaces remain the same in browser and desktop.
- Existing PostgreSQL, pgvector retrieval, migrations, checkpointing, and
  Docker sandbox code remain authoritative.
- The API is never published beyond loopback, and its Docker SDK access is not
  granted through a container socket mount.
- The native process layer exposes named operations instead of shell strings.
- PostgreSQL data and desktop workspace/checkpoint data have independent,
  documented backup and uninstall behavior.

### Trade-offs and limits

- Docker Desktop remains required for PostgreSQL and Docker sandbox execution.
- The packaged Python sidecar and Tauri shell increase installer size.
- The API sidecar runs with the user's Windows account and can access the
  configured Docker daemon; Kuractus continues to require all user code to pass
  through the existing restricted sandbox runtime.
- Windows Credential Manager protects secrets at rest. Docker stores the
  PostgreSQL credential in its container configuration while the database is
  running, as required by the current Postgres image contract.
- Automatic updates and code signing are deferred until a signing/release
  process is established.

## Alternatives rejected

- **Electron:** capable but adds a bundled Chromium/Node runtime and a broader
  renderer IPC security surface without a feature Kuractus needs over Tauri.
- **API inside Compose with a mounted Docker socket:** would give the API
  container daemon-level control and weaken the boundary between the runtime
  and sandbox execution.
- **SQLite-only sidecar:** rejected because changing away from pgvector would
  silently reduce the tested retrieval/data path.
