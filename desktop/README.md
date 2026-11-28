# AURA Desktop for Windows

AURA Desktop packages the existing React workspace in a Tauri 2 application.
It starts the existing FastAPI/LangGraph runtime as a bundled Windows sidecar
and manages the Postgres/pgvector service through a fixed Compose definition.
The app does not depend on a Git checkout.

## Runtime requirements

- Windows 11 x64 and WebView2 Runtime.
- Docker Desktop with its Linux container engine running.
- Network access on the first runtime start to pull the exact pgvector image
  referenced by `runtime/compose.yaml`.

AURA never installs Docker Engine. If Docker is missing or stopped, the app
shows the prerequisite and the exact diagnostic needed to continue.

## Development build

From the repository root, build the API sidecar and install the frontend/Tauri
dependencies, then run `npx tauri dev` from `desktop/`. The Windows CI workflow
builds the same sidecar and the NSIS installer. See
[`docs/windows-desktop.md`](../docs/windows-desktop.md) for reproducible build,
runtime, backup/restore, security, and D1-D7 dogfood instructions.

## Data locations

- PostgreSQL: Docker volume `aura_desktop_postgres_data`.
- LangGraph checkpoints: `%LOCALAPPDATA%\AURA\checkpoints`.
- Workspace files: `%LOCALAPPDATA%\AURA\workspace`.
- Desktop preferences and folder references: `%LOCALAPPDATA%\AURA`.

Stopping or uninstalling AURA Desktop preserves these stores. Runtime shutdown
uses `docker compose stop`; there is no `down -v` command in the application.
