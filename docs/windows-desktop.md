# AURA Desktop for Windows

## Runtime design

AURA Desktop is a Tauri 2 application that hosts the existing React/Vite
workspace and starts the existing FastAPI/LangGraph application as a packaged
Windows sidecar. Rust owns process lifecycle, Docker Compose, OS integration,
and the narrow filesystem commands. The renderer cannot run shell commands.

PostgreSQL with pgvector remains the durable database. A fixed Compose project
starts only the pinned Postgres image; the API runs as the desktop user's
process and keeps using the existing Docker sandbox runtime. Docker Desktop's
Linux engine is therefore required for the database and sandbox. AURA does not
install Docker Engine or expose the Docker socket to an API container.

The packaged API binds to `127.0.0.1:17890`. Its private database service binds
to `127.0.0.1:15432` and stores data in the dedicated volume
`aura_desktop_postgres_data`. These are separate from the repository Compose
ports and volumes. Normal stop, quit, backup, restore, and uninstall never
remove that volume.

The shell supervises the API process with a Windows job object configured to
terminate the sidecar if AURA exits unexpectedly. Runtime status checks the
child process and `/ready`; a lost API is `error`, while a live API with an
unavailable database/checkpointer is `degraded`. Startup detects API port
conflicts before starting services and translates PostgreSQL bind conflicts
into an actionable message.

## Model and workspace defaults

A fresh desktop install starts with no model provider selected and no model ID
assumed. AI runs report that a provider must be configured instead of returning
deterministic mock text. The offline Mock provider remains available as an
explicit demo choice. Local Ollama and LM Studio models are discovered from the
desktop runtime and can be selected in Routing Studio; cloud-compatible
endpoints require the exact endpoint URL and model ID to be entered in desktop
settings.

Bundled demo projects, chats, notes, automations, and library files remain part
of the browser prototype only. Desktop startup filters those fixtures from its
initial state and from any older browser storage, while retaining imported and
live records.

## Build and install

Requirements: Windows 11 x64, WebView2 Runtime, Docker Desktop with the Linux
engine running, Python 3.12, Node 24, Rust stable, and the Visual Studio C++
Build Tools workload.

From the repository root in PowerShell:

```powershell
npm ci --prefix web
python -m pip install -r desktop/requirements-sidecar.txt
python desktop/scripts/make_icon.py
./desktop/scripts/build_sidecar.ps1
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml -- --check
cargo test --manifest-path desktop/src-tauri/Cargo.toml
Push-Location desktop/src-tauri
..\..\web\node_modules\.bin\tauri.cmd build --bundles nsis
Pop-Location
```

The reproducible CI job builds an unsigned per-user NSIS installer and writes a
SHA-256 checksum alongside it. Installers are workflow artifacts, not public
releases. The app is not code-signed and has no automatic updater; Windows may
show the standard unsigned-app warning. Builds do not need a provider API key.

## Data, files, and credentials

- Postgres: `aura_desktop_postgres_data` Docker volume.
- Workspace and LangGraph checkpoints: `%LOCALAPPDATA%\AURA\workspace` and
  `%LOCALAPPDATA%\AURA\checkpoints`.
- Preferences and connected-folder references:
  `%APPDATA%\AURA` (with Tauri's app-config directory as fallback).
- API token, Postgres password, and optional provider key: Windows Credential
  Manager. The backup archive excludes these credentials.

Folder connections store an opaque ID and selected root path. Indexing reads
file metadata only. File bytes are read only after opening a selected result or
dropping a file on the AURA window. Dropped files are limited to five files,
25 MB per file, 40 MB total, and reject symlinks/junctions. The UI does not
receive native absolute paths from drag-and-drop. Imported content is stored
locally in the current browser storage path; metadata references can sync to
the workspace graph when the API is available. Connected folders are never
bulk copied or uploaded.

## Runtime operation and recovery

The tray menu can show the main window, start the runtime, open runtime
settings, or quit. Closing to tray is enabled by default. Start with Windows is
disabled until the user opts in. Notifications are also opt-in and use generic
text without prompts, file names, or model responses.

The desktop panel reports Docker, API, and readiness failures. API port
conflicts identify port `17890`; database bind conflicts identify port
`15432`. If the API exits while the window remains open, periodic health checks
show the exit code and offer restart. If AURA itself is terminated, the Windows
job object closes the API child; Compose data remains available for the next
launch.

Backup creates a `.aurabackup` archive containing a PostgreSQL dump, workspace
files, and checkpoints. Credentials and connected external-folder contents
are excluded. Restore asks for confirmation and first creates a safety backup.
Uninstalling the app removes the installed application files only; it does not
remove the Docker volume, AppData, checkpoints, workspace, or backup archives.
There is no in-app data deletion command in this milestone.

## Verification record

Automated CI evidence and interactive dogfood evidence are tracked separately.
Do not mark a dogfood item passed based on compilation or unit tests.

| Check | Required evidence | Result |
| --- | --- | --- |
| D1 Fresh install | Install the CI artifact, launch from Start Menu, see the production UI, start services, and observe `/ready` | Pending Windows dogfood |
| D2 Runtime continuity | Close to tray, reopen, quit, relaunch, and confirm a persisted object remains | Pending Windows dogfood |
| D3 Filesystem | Connect a folder, restart, reopen one supported file, send selected text, confirm unrelated files remain untouched | Pending Windows dogfood |
| D4 Notifications | Exercise approval and completed/failed run notifications with opt-in and opt-out; inspect generic text | Pending Windows dogfood |
| D5 Runtime failures | Exercise Docker missing/stopped, API and DB port conflicts, backend exit, and database unavailable; inspect diagnostics | Pending Windows dogfood |
| D6 Recovery | Create/restore a backup, verify the safety archive and preserved volume, uninstall/reinstall without data loss | Pending Windows dogfood |
| D7 Security | Verify loopback listeners, native scoped file access, no renderer shell command, and Credential Manager storage | Pending Windows dogfood |

Windows CI runs frontend tests/build, desktop API/backup tests, frozen-sidecar
self-test, Rust format/tests, and NSIS packaging on the exact PR head. CI cannot
prove Start Menu installation, tray behavior, real Windows notifications,
Credential Manager behavior, or uninstall persistence; record those only after
the corresponding interactive checks run.
