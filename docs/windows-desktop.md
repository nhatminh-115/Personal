# Kuractus Desktop for Windows

## Runtime design

Kuractus Desktop is a Tauri 2 application that hosts the existing React/Vite
workspace and starts the existing FastAPI/LangGraph application as a packaged
Windows sidecar. Rust owns process lifecycle, Docker Compose, OS integration,
and the narrow filesystem commands. The renderer cannot run shell commands.

PostgreSQL with pgvector remains the durable database. A fixed Compose project
starts only the pinned Postgres image; the API runs as the desktop user's
process and keeps using the existing Docker sandbox runtime. Docker Desktop's
Linux engine is therefore required for the database and sandbox. Kuractus does not
install Docker Engine or expose the Docker socket to an API container.

The packaged API binds to `127.0.0.1:17890`. Its private database service binds
to `127.0.0.1:15432` and stores data in the dedicated volume
`aura_desktop_postgres_data`. These are separate from the repository Compose
ports and volumes. Normal stop, quit, backup, restore, and uninstall never
remove that volume.

The packaged frontend sends API requests to `http://127.0.0.1:17890` by
default. Browser builds keep relative `/v1` requests and use the Vite development
proxy. `VITE_AURA_API_BASE_URL` can override the API base URL in either mode.

The shell supervises the API process with a Windows job object configured to
terminate the sidecar if Kuractus exits unexpectedly. Runtime status checks the
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

The per-user NSIS package installs the app under `%LOCALAPPDATA%\Kuractus` and
uses Kuractus for its executable, Start Menu/Search shortcuts, and Installed
Apps entry. Existing data stays under the established `%LOCALAPPDATA%\AURA` and
`%APPDATA%\AURA` paths. The bundle identifier, Compose project, and volume
identifiers remain unchanged for compatibility. The installer checks for both
the previous AURA executable and the Kuractus executable and exits without
terminating either process. The icon generator derives the native Windows icon
from `desktop/src-tauri/icons/kuractus-icon.png`.

The reproducible CI job builds an unsigned per-user NSIS installer and writes a
SHA-256 checksum alongside it. Installers are workflow artifacts, not public
releases. The app is not code-signed and has no automatic updater; Windows may
show the standard unsigned-app warning. Builds do not need a provider API key.

## Data, files, and credentials

- Postgres: `aura_desktop_postgres_data` Docker volume.
- App installation: `%LOCALAPPDATA%\Kuractus`.
- Workspace and LangGraph checkpoints: `%LOCALAPPDATA%\AURA\workspace` and
  `%LOCALAPPDATA%\AURA\checkpoints`.
- Preferences and connected-folder references:
  `%APPDATA%\AURA` (with Tauri's app-config directory as fallback).
- API token, Postgres password, and optional provider key: Windows Credential
  Manager. The backup archive excludes these credentials.

The desktop shell shares one in-memory API token between the renderer and the
sidecar. First-launch token creation is serialized so concurrent startup paths
cannot give the renderer and API different credentials.

Folder connections store an opaque ID and selected root path. Indexing reads
file metadata only. File bytes are read only after opening a selected result or
dropping a file on the Kuractus window. Dropped files are limited to five files,
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
The global shortcut is managed when its selected value changes; saving unrelated
preferences does not register the same shortcut a second time.

The desktop panel reports Docker, API, and readiness failures. API port
conflicts identify port `17890`; database bind conflicts identify port
`15432`. If the API exits while the window remains open, periodic health checks
show the exit code and offer restart. If Kuractus itself is terminated, the Windows
job object closes the API child; Compose data remains available for the next
launch.

Backup creates a `.aurabackup` archive containing a PostgreSQL dump, workspace
files, and checkpoints. Credentials and connected external-folder contents
are excluded. Restore asks for confirmation and first creates a safety backup.
Uninstalling the app removes the installed application files only; it does not
remove the Docker volume, AppData, checkpoints, workspace, or backup archives.
There is no in-app data deletion command in this milestone.

## Verification record

Windows Desktop verification is CI-first and must not control a developer's
primary desktop. Use the read-only host snapshot and the D1–D7 status matrix in
[`windows-desktop-testing.md`](windows-desktop-testing.md). Tray, native
notification, drag-and-drop, restore, uninstall, and first-launch UI scenarios
that need visible interaction are deferred until an isolated Windows VM or test
session is available.

Windows CI runs frontend tests/build, desktop API/backup tests, frozen-sidecar
self-test, Rust format/tests, and NSIS packaging on the exact PR head. CI proves
the code and package checks only; it does not by itself prove installed runtime
health or the isolated Windows behaviors listed above.
