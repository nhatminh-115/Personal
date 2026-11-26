use keyring::Entry;
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_dialog::DialogExt;
use uuid::Uuid;

const SERVICE_NAME: &str = "com.aura.personal.desktop";
const API_PORT: u16 = 17890;
const COMPOSE_PROJECT: &str = "aura-desktop";

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimePhase {
    Stopped,
    Starting,
    Ready,
    Degraded,
    Stopping,
    Error,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeSnapshot {
    pub phase: RuntimePhase,
    pub message: String,
    pub api_url: String,
    pub docker_available: bool,
    pub provider: String,
    pub base_url: String,
    pub model: String,
    pub global_shortcut: String,
    pub close_to_tray: bool,
    pub autostart: bool,
    pub notifications: bool,
    pub has_provider_key: bool,
    pub provider_connections: Vec<ProviderConnectionStatus>,
    pub active_provider_connection_id: Option<String>,
    pub logs: Vec<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderConnection {
    pub id: String,
    pub name: String,
    pub base_url: String,
    pub model: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderConnectionStatus {
    pub id: String,
    pub name: String,
    pub base_url: String,
    pub model: String,
    pub has_api_key: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct DesktopPreferences {
    pub provider: String,
    pub base_url: String,
    pub model: String,
    pub close_to_tray: bool,
    pub autostart: bool,
    pub notifications: bool,
    pub global_shortcut: String,
    #[serde(default)]
    pub provider_connections: Vec<ProviderConnection>,
    #[serde(default)]
    pub active_provider_connection_id: Option<String>,
}

impl Default for DesktopPreferences {
    fn default() -> Self {
        Self {
            provider: "unconfigured".into(),
            base_url: String::new(),
            model: String::new(),
            close_to_tray: true,
            autostart: false,
            notifications: false,
            global_shortcut: "CommandOrControl+Alt+A".into(),
            provider_connections: Vec::new(),
            active_provider_connection_id: None,
        }
    }
}

struct RuntimeInner {
    phase: RuntimePhase,
    message: String,
    docker_available: bool,
    child: Option<Child>,
    api_token: Option<String>,
    #[cfg(windows)]
    child_job: Option<std::os::windows::io::OwnedHandle>,
    logs: VecDeque<String>,
    preferences: DesktopPreferences,
}

#[derive(Clone)]
pub struct DesktopRuntime(Arc<Mutex<RuntimeInner>>);

impl Default for DesktopRuntime {
    fn default() -> Self {
        Self(Arc::new(Mutex::new(RuntimeInner {
            phase: RuntimePhase::Stopped,
            message: "Kuractus Desktop is stopped.".into(),
            docker_available: false,
            child: None,
            api_token: None,
            #[cfg(windows)]
            child_job: None,
            logs: VecDeque::with_capacity(200),
            preferences: DesktopPreferences::default(),
        })))
    }
}

impl DesktopRuntime {
    fn entry(key: &str) -> Result<Entry, String> {
        Entry::new(SERVICE_NAME, key)
            .map_err(|error| format!("Windows Credential Manager: {error}"))
    }

    fn api_token_with(
        &self,
        load: impl FnOnce() -> Result<String, String>,
    ) -> Result<String, String> {
        let mut inner = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(token) = inner.api_token.as_ref() {
            return Ok(token.clone());
        }
        let token = load()?;
        inner.api_token = Some(token.clone());
        Ok(token)
    }

    fn api_token(&self) -> Result<String, String> {
        self.api_token_with(|| Self::ensure_secret("api_token"))
    }

    fn ensure_secret(key: &str) -> Result<String, String> {
        let entry = Self::entry(key)?;
        match entry.get_password() {
            Ok(secret) if !secret.is_empty() => Ok(secret),
            Ok(_) | Err(keyring::Error::NoEntry) => {
                let secret = format!("{}{}", Uuid::new_v4().simple(), Uuid::new_v4().simple());
                entry
                    .set_password(&secret)
                    .map_err(|error| format!("Could not store a desktop credential: {error}"))?;
                Ok(secret)
            }
            Err(error) => Err(format!("Could not read a desktop credential: {error}")),
        }
    }

    fn read_secret(key: &str) -> Result<Option<String>, String> {
        match Self::entry(key)?.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(error) => Err(format!("Could not read a desktop credential: {error}")),
        }
    }

    fn provider_secret_key(connection_id: Option<&str>) -> String {
        match connection_id {
            Some("legacy") | None => "provider_api_key".into(),
            Some(id) => format!("provider_api_key_{id}"),
        }
    }

    fn provider_connections_for(preferences: &DesktopPreferences) -> Vec<ProviderConnection> {
        if !preferences.provider_connections.is_empty() {
            let mut connections = preferences.provider_connections.clone();
            let active_id = preferences
                .active_provider_connection_id
                .as_deref()
                .unwrap_or("legacy");
            if preferences.provider == "openai"
                && !connections
                    .iter()
                    .any(|connection| connection.id == active_id)
            {
                connections.push(ProviderConnection {
                    id: active_id.into(),
                    name: "OpenAI-compatible API".into(),
                    base_url: preferences.base_url.clone(),
                    model: preferences.model.clone(),
                });
            }
            return connections;
        }
        if preferences.provider == "openai" {
            return vec![ProviderConnection {
                id: "legacy".into(),
                name: "OpenAI-compatible API".into(),
                base_url: preferences.base_url.clone(),
                model: preferences.model.clone(),
            }];
        }
        Vec::new()
    }

    fn active_provider_key(preferences: &DesktopPreferences) -> Result<String, String> {
        let secret_key =
            Self::provider_secret_key(preferences.active_provider_connection_id.as_deref());
        Ok(Self::read_secret(&secret_key)?.unwrap_or_default())
    }

    pub fn aura_config_dir(app: &AppHandle) -> Result<PathBuf, String> {
        let directory = std::env::var_os("APPDATA")
            .map(PathBuf::from)
            .unwrap_or(
                app.path()
                    .app_config_dir()
                    .map_err(|error| error.to_string())?,
            )
            .join("AURA");
        std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
        Ok(directory)
    }

    pub fn aura_local_data_dir(app: &AppHandle) -> Result<PathBuf, String> {
        let directory = std::env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or(
                app.path()
                    .app_local_data_dir()
                    .map_err(|error| error.to_string())?,
            )
            .join("AURA");
        std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
        Ok(directory)
    }

    fn preference_path(app: &AppHandle) -> Result<PathBuf, String> {
        Ok(Self::aura_config_dir(app)?.join("desktop-preferences.json"))
    }

    pub fn load_preferences(app: &AppHandle) -> DesktopPreferences {
        let Ok(path) = Self::preference_path(app) else {
            return DesktopPreferences::default();
        };
        std::fs::read(path)
            .ok()
            .and_then(|bytes| serde_json::from_slice(&bytes).ok())
            .unwrap_or_default()
    }

    fn save_preferences(app: &AppHandle, preferences: &DesktopPreferences) -> Result<(), String> {
        let path = Self::preference_path(app)?;
        let temporary = path.with_extension("json.tmp");
        let bytes = serde_json::to_vec_pretty(preferences).map_err(|error| error.to_string())?;
        std::fs::write(&temporary, bytes).map_err(|error| error.to_string())?;
        std::fs::rename(&temporary, &path).map_err(|error| error.to_string())
    }

    pub fn snapshot(&self) -> RuntimeSnapshot {
        let inner = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let preferences = &inner.preferences;
        let provider_connections = Self::provider_connections_for(preferences)
            .into_iter()
            .map(|connection| ProviderConnectionStatus {
                has_api_key: Self::read_secret(&Self::provider_secret_key(Some(&connection.id)))
                    .ok()
                    .flatten()
                    .is_some(),
                id: connection.id,
                name: connection.name,
                base_url: connection.base_url,
                model: connection.model,
            })
            .collect();
        let active_provider_connection_id = preferences
            .active_provider_connection_id
            .clone()
            .or_else(|| (preferences.provider == "openai").then(|| "legacy".into()));
        RuntimeSnapshot {
            phase: inner.phase.clone(),
            message: inner.message.clone(),
            api_url: format!("http://127.0.0.1:{API_PORT}"),
            docker_available: inner.docker_available,
            provider: preferences.provider.clone(),
            base_url: preferences.base_url.clone(),
            model: preferences.model.clone(),
            global_shortcut: preferences.global_shortcut.clone(),
            close_to_tray: preferences.close_to_tray,
            autostart: preferences.autostart,
            notifications: preferences.notifications,
            has_provider_key: active_provider_connection_id
                .as_deref()
                .and_then(|id| {
                    Self::read_secret(&Self::provider_secret_key(Some(id)))
                        .ok()
                        .flatten()
                })
                .is_some(),
            provider_connections,
            active_provider_connection_id,
            logs: inner.logs.iter().cloned().collect(),
        }
    }

    fn log(&self, message: impl Into<String>) {
        let mut inner = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if inner.logs.len() == 200 {
            inner.logs.pop_front();
        }
        let message = message.into();
        let provider_key = Self::active_provider_key(&inner.preferences).unwrap_or_default();
        let postgres_password = Self::read_secret("postgres_password")
            .ok()
            .flatten()
            .unwrap_or_default();
        let api_token = Self::read_secret("api_token")
            .ok()
            .flatten()
            .unwrap_or_default();
        let message = [provider_key, postgres_password, api_token]
            .into_iter()
            .filter(|secret| !secret.is_empty())
            .fold(message, |line, secret| line.replace(&secret, "[redacted]"));
        inner.logs.push_back(message);
    }

    fn set_phase(&self, phase: RuntimePhase, message: impl Into<String>, docker_available: bool) {
        let mut inner = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        inner.phase = phase;
        inner.message = message.into();
        inner.docker_available = docker_available;
    }

    fn settings(&self) -> DesktopPreferences {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .preferences
            .clone()
    }

    pub fn apply_preferences(&self, preferences: DesktopPreferences) {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .preferences = preferences;
    }

    fn child_alive(&self) -> bool {
        let mut inner = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        inner
            .child
            .as_mut()
            .is_some_and(|child| matches!(child.try_wait(), Ok(None)))
    }

    pub fn refresh_health(&self) {
        let child_state = {
            let mut inner = self
                .0
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if !matches!(&inner.phase, RuntimePhase::Ready | RuntimePhase::Degraded) {
                return;
            }
            inner.child.as_mut().map(|child| child.try_wait())
        };

        match child_state {
            None => {
                self.set_phase(
                    RuntimePhase::Error,
                    "The Kuractus API process is no longer supervised. Restart the runtime to recover.",
                    self.snapshot().docker_available,
                );
                self.log("The Kuractus API process handle was lost while the runtime was active.");
            }
            Some(Err(error)) => self.set_phase(
                RuntimePhase::Degraded,
                format!("Could not verify the Kuractus API process: {error}"),
                self.snapshot().docker_available,
            ),
            Some(Ok(Some(exit))) => {
                {
                    let mut inner = self
                        .0
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner());
                    inner.child = None;
                    #[cfg(windows)]
                    {
                        inner.child_job = None;
                    }
                }
                let code = exit
                    .code()
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "unknown".into());
                let message = format!(
                    "The Kuractus API stopped unexpectedly (exit code {code}). Restart the runtime to recover."
                );
                self.set_phase(RuntimePhase::Error, message.clone(), true);
                self.log(message);
            }
            Some(Ok(None)) => match request_ready() {
                Ok(true) => self.set_phase(
                    RuntimePhase::Ready,
                    "Kuractus is ready. Your data stays on this PC.",
                    true,
                ),
                Ok(false) => self.set_phase(
                    RuntimePhase::Degraded,
                    "The Kuractus API is running, but its database or checkpoint service is not ready. Check Docker Desktop, then restart the runtime.",
                    true,
                ),
                Err(_) => self.set_phase(
                    RuntimePhase::Degraded,
                    "The Kuractus API is running, but the local readiness check failed. Check the runtime log, then restart if needed.",
                    true,
                ),
            },
        }
    }

    pub fn restart(&self, app: &AppHandle) -> Result<RuntimeSnapshot, String> {
        self.stop(app)?;
        self.start(app)
    }

    pub fn start(&self, app: &AppHandle) -> Result<RuntimeSnapshot, String> {
        if self.child_alive() && matches!(self.snapshot().phase, RuntimePhase::Ready) {
            return Ok(self.snapshot());
        }
        if matches!(
            self.snapshot().phase,
            RuntimePhase::Starting | RuntimePhase::Stopping
        ) {
            return Ok(self.snapshot());
        }
        {
            let mut inner = self
                .0
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if let Some(mut stale) = inner.child.take() {
                let _ = stale.kill();
                let _ = stale.wait();
            }
            #[cfg(windows)]
            {
                inner.child_job = None;
            }
        }
        self.set_phase(RuntimePhase::Starting, "Checking Docker Desktop…", false);
        if let Err(message) = ensure_loopback_port_available(API_PORT, "Kuractus API") {
            self.set_phase(RuntimePhase::Error, message.clone(), false);
            self.log(message.clone());
            return Err(message);
        }
        let api_token = self.api_token()?;
        let postgres_password = Self::ensure_secret("postgres_password")?;
        let mut docker = Command::new("docker");
        docker
            .args(["info", "--format", "{{.ServerVersion}}"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let docker_result = docker.output();
        let docker_version = match docker_result {
            Ok(output) if output.status.success() => {
                String::from_utf8_lossy(&output.stdout).trim().to_owned()
            }
            Ok(output) => {
                let detail = String::from_utf8_lossy(&output.stderr).trim().to_owned();
                let message = if detail.is_empty() {
                    "Docker Desktop is installed but its Linux container engine is not running. Start Docker Desktop, wait for Engine running, then retry.".into()
                } else {
                    format!("Docker Desktop is unavailable: {detail}")
                };
                self.set_phase(RuntimePhase::Error, message.clone(), false);
                self.log(message.clone());
                return Err(message);
            }
            Err(error) => {
                let message = if error.kind() == std::io::ErrorKind::NotFound {
                    "Docker Desktop is required. Install it and start the Linux container engine; Kuractus will not install Docker for you.".into()
                } else {
                    format!("Could not connect to Docker Desktop: {error}")
                };
                self.set_phase(RuntimePhase::Error, message.clone(), false);
                self.log(message.clone());
                return Err(message);
            }
        };
        self.set_phase(
            RuntimePhase::Starting,
            format!("Docker Engine {docker_version} is ready. Starting Kuractus data services…"),
            true,
        );

        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?;
        let compose_file = resource_dir.join("runtime").join("compose.yaml");
        if !compose_file.is_file() {
            let message = format!(
                "The packaged runtime definition is missing: {}",
                compose_file.display()
            );
            self.set_phase(RuntimePhase::Error, message.clone(), true);
            return Err(message);
        }
        let compose = Command::new("docker")
            .args(["compose", "--project-name", COMPOSE_PROJECT, "--file"])
            .arg(&compose_file)
            .args(["up", "-d", "--wait"])
            .env("AURA_DESKTOP_POSTGRES_PASSWORD", &postgres_password)
            .output()
            .map_err(|error| format!("Could not start Kuractus's PostgreSQL service: {error}"))?;
        if !compose.status.success() {
            let detail = redact(
                &String::from_utf8_lossy(&compose.stderr),
                &postgres_password,
            );
            let message = docker_compose_start_error(&detail);
            self.set_phase(RuntimePhase::Error, message.clone(), true);
            self.log(format!("PostgreSQL startup failed: {message}"));
            return Err(message);
        }
        self.log("PostgreSQL/pgvector is healthy on loopback port 15432.");

        let local_data = Self::aura_local_data_dir(app)?;
        let workspace = local_data.join("workspace");
        let checkpoints = local_data.join("checkpoints");
        let configuration = Self::aura_config_dir(app)?;
        for directory in [&workspace, &checkpoints, &configuration] {
            std::fs::create_dir_all(directory)
                .map_err(|error| format!("Could not prepare Kuractus data directory: {error}"))?;
        }
        let database_url = format!(
            "postgresql+asyncpg://aura_desktop:{postgres_password}@127.0.0.1:15432/aura_desktop"
        );
        self.apply_preferences(Self::load_preferences(app));
        let settings = self.settings();
        let provider_key = Self::active_provider_key(&settings)?;
        let sidecar = resource_dir.join("aura-api.exe");
        if !sidecar.is_file() {
            let message = format!(
                "The packaged Kuractus runtime is missing: {}",
                sidecar.display()
            );
            self.set_phase(RuntimePhase::Error, message.clone(), true);
            return Err(message);
        }
        let sidecar_env = |command: &mut Command| {
            command
                .env("DESKTOP_MODE", "true")
                .env("AURA_API_TOKEN", api_token.as_str())
                .env("DATABASE_URL", &database_url)
                .env(
                    "CHECKPOINT_DB_PATH",
                    checkpoints.join("aura_checkpoints.db"),
                )
                .env("AURA_WORKSPACE_ROOT", &workspace)
                .env("MCP_CONFIG_PATH", configuration.join("mcp_servers.json"))
                .env("AURA_DESKTOP_CONFIG_DIR", &configuration)
                .env("AURA_DESKTOP_LOCAL_DATA_DIR", &local_data)
                .env("AURA_DESKTOP_COMPOSE_FILE", &compose_file)
                .env("AURA_DESKTOP_POSTGRES_PASSWORD", &postgres_password)
                .env(
                    "CORS_ALLOWED_ORIGINS",
                    "http://tauri.localhost,https://tauri.localhost,tauri://localhost",
                )
                .env("EMBEDDING_PROVIDER", "mock")
                .env("MODEL_PROVIDER", &settings.provider)
                .env("OPENAI_BASE_URL", &settings.base_url)
                .env("OPENAI_MODEL_NAME", &settings.model)
                .env("OPENAI_API_KEY", &provider_key);
        };
        let migration = Command::new(&sidecar);
        let mut migration = migration;
        sidecar_env(&mut migration);
        let migration_output = migration
            .arg("--desktop-migrate")
            .output()
            .map_err(|error| format!("Could not run desktop database migrations: {error}"))?;
        if !migration_output.status.success() {
            let message = redact(
                &String::from_utf8_lossy(&migration_output.stderr),
                &postgres_password,
            );
            self.set_phase(
                RuntimePhase::Error,
                format!("Database migration failed: {message}"),
                true,
            );
            self.log(format!("Database migration failed: {message}"));
            return Err(message);
        }
        self.log("Database migrations are current.");

        let mut process = Command::new(&sidecar);
        sidecar_env(&mut process);
        let process = process
            .args(["--desktop-serve", "--host", "127.0.0.1", "--port", "17890"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            process.creation_flags(0x08000000);
        }
        let mut child = process
            .spawn()
            .map_err(|error| format!("Could not start the Kuractus runtime: {error}"))?;
        #[cfg(windows)]
        let child_job = match create_kill_on_close_job(&child) {
            Ok(job) => job,
            Err(message) => {
                let _ = child.kill();
                let _ = child.wait();
                self.set_phase(RuntimePhase::Error, message.clone(), true);
                self.log(message.clone());
                return Err(message);
            }
        };
        {
            let mut inner = self
                .0
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            inner.child = Some(child);
            #[cfg(windows)]
            {
                inner.child_job = Some(child_job);
            }
        }
        self.set_phase(
            RuntimePhase::Starting,
            "Waiting for the Kuractus API to become ready…",
            true,
        );
        match wait_until_ready(&self.0) {
            Ok(()) => {
                self.set_phase(
                    RuntimePhase::Ready,
                    "Kuractus is ready. Your data stays on this PC.",
                    true,
                );
                self.log("Kuractus API and durable runtime are ready on loopback port 17890.");
                Ok(self.snapshot())
            }
            Err(message) => {
                self.set_phase(RuntimePhase::Error, message.clone(), true);
                self.log(message.clone());
                Err(message)
            }
        }
    }

    pub fn start_postgres_for_maintenance(app: &AppHandle) -> Result<(), String> {
        let password = Self::ensure_secret("postgres_password")?;
        let compose = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?
            .join("runtime")
            .join("compose.yaml");
        let output = Command::new("docker")
            .args(["compose", "--project-name", COMPOSE_PROJECT, "--file"])
            .arg(compose)
            .args(["up", "-d", "--wait", "postgres"])
            .env("AURA_DESKTOP_POSTGRES_PASSWORD", &password)
            .output()
            .map_err(|error| format!("Could not start the Kuractus database service: {error}"))?;
        if !output.status.success() {
            return Err(redact(&String::from_utf8_lossy(&output.stderr), &password));
        }
        Ok(())
    }

    pub fn stop_postgres_after_maintenance(app: &AppHandle) -> Result<(), String> {
        let password = Self::read_secret("postgres_password")?.unwrap_or_default();
        let compose = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?
            .join("runtime")
            .join("compose.yaml");
        let output = Command::new("docker")
            .args(["compose", "--project-name", COMPOSE_PROJECT, "--file"])
            .arg(compose)
            .args(["stop", "--timeout", "15", "postgres"])
            .env("AURA_DESKTOP_POSTGRES_PASSWORD", &password)
            .output()
            .map_err(|error| format!("Could not pause the Kuractus database service: {error}"))?;
        if !output.status.success() {
            return Err(redact(&String::from_utf8_lossy(&output.stderr), &password));
        }
        Ok(())
    }

    pub fn run_sidecar_operation(
        &self,
        app: &AppHandle,
        operation: &str,
        path: &Path,
    ) -> Result<String, String> {
        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|error| error.to_string())?;
        let sidecar = resource_dir.join("aura-api.exe");
        let local_data = Self::aura_local_data_dir(app)?;
        let workspace = local_data.join("workspace");
        let checkpoints = local_data.join("checkpoints");
        let configuration = Self::aura_config_dir(app)?;
        let compose_file = resource_dir.join("runtime").join("compose.yaml");
        let postgres_password = Self::ensure_secret("postgres_password")?;
        let api_token = self.api_token()?;
        let database_url = format!(
            "postgresql+asyncpg://aura_desktop:{postgres_password}@127.0.0.1:15432/aura_desktop"
        );
        let preferences = Self::load_preferences(app);
        let provider_key = Self::active_provider_key(&preferences)?;
        let mut command = Command::new(sidecar);
        command
            .arg(operation)
            .arg(path)
            .env("DESKTOP_MODE", "true")
            .env("AURA_API_TOKEN", &api_token)
            .env("AURA_DESKTOP_POSTGRES_PASSWORD", &postgres_password)
            .env("DATABASE_URL", database_url)
            .env(
                "CHECKPOINT_DB_PATH",
                checkpoints.join("aura_checkpoints.db"),
            )
            .env("AURA_WORKSPACE_ROOT", &workspace)
            .env("AURA_DESKTOP_LOCAL_DATA_DIR", &local_data)
            .env("AURA_DESKTOP_CONFIG_DIR", &configuration)
            .env("AURA_DESKTOP_COMPOSE_FILE", &compose_file)
            .env("MCP_CONFIG_PATH", configuration.join("mcp_servers.json"))
            .env(
                "CORS_ALLOWED_ORIGINS",
                "http://tauri.localhost,https://tauri.localhost,tauri://localhost",
            )
            .env("EMBEDDING_PROVIDER", "mock")
            .env("MODEL_PROVIDER", preferences.provider)
            .env("OPENAI_BASE_URL", preferences.base_url)
            .env("OPENAI_MODEL_NAME", preferences.model)
            .env("OPENAI_API_KEY", &provider_key)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let output = command
            .output()
            .map_err(|error| format!("Could not run Kuractus's local data operation: {error}"))?;
        if !output.status.success() {
            let mut message = String::from_utf8_lossy(&output.stderr).trim().to_owned();
            for secret in [&postgres_password, &api_token, &provider_key] {
                if !secret.is_empty() {
                    message = message.replace(secret, "[redacted]");
                }
            }
            return Err(if message.is_empty() {
                format!(
                    "Kuractus local operation failed (exit code {}).",
                    output.status.code().unwrap_or(-1)
                )
            } else {
                message
            });
        }
        Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
    }

    pub fn stop(&self, app: &AppHandle) -> Result<RuntimeSnapshot, String> {
        let phase = self.snapshot().phase;
        if matches!(phase, RuntimePhase::Stopped) {
            return Ok(self.snapshot());
        }
        self.set_phase(
            RuntimePhase::Stopping,
            "Stopping the Kuractus runtime and pausing PostgreSQL…",
            self.snapshot().docker_available,
        );
        let token = Self::read_secret("api_token")
            .ok()
            .flatten()
            .unwrap_or_default();
        let _ = post_shutdown(&token);
        let deadline = Instant::now() + Duration::from_secs(15);
        loop {
            let exited = {
                let mut inner = self
                    .0
                    .lock()
                    .unwrap_or_else(|poisoned| poisoned.into_inner());
                match inner.child.as_mut() {
                    Some(child) => match child.try_wait() {
                        Ok(Some(_)) => {
                            inner.child = None;
                            true
                        }
                        _ => false,
                    },
                    None => true,
                }
            };
            if exited || Instant::now() >= deadline {
                break;
            }
            thread::sleep(Duration::from_millis(250));
        }
        {
            let mut inner = self
                .0
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if let Some(mut child) = inner.child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
            #[cfg(windows)]
            {
                inner.child_job = None;
            }
        }
        if let Ok(resource_dir) = app.path().resource_dir() {
            let compose_file = resource_dir.join("runtime").join("compose.yaml");
            if compose_file.is_file() {
                let password = Self::read_secret("postgres_password")?.unwrap_or_default();
                let output = Command::new("docker")
                    .args(["compose", "--project-name", COMPOSE_PROJECT, "--file"])
                    .arg(compose_file)
                    .args(["stop", "--timeout", "15"])
                    .env("AURA_DESKTOP_POSTGRES_PASSWORD", &password)
                    .output();
                if let Ok(output) = output {
                    if !output.status.success() {
                        let message = redact(&String::from_utf8_lossy(&output.stderr), &password);
                        self.log(format!("PostgreSQL stop warning: {message}"));
                    }
                }
            }
        }
        self.set_phase(
            RuntimePhase::Stopped,
            "Kuractus is stopped. Local data and the database volume are preserved.",
            true,
        );
        self.log("Kuractus runtime stopped; PostgreSQL volume and local files were preserved.");
        Ok(self.snapshot())
    }
}

fn redact(value: &str, secret: &str) -> String {
    if secret.is_empty() {
        value.trim().to_owned()
    } else {
        value.replace(secret, "[redacted]").trim().to_owned()
    }
}

fn ensure_loopback_port_available(port: u16, service: &str) -> Result<(), String> {
    TcpListener::bind(SocketAddr::from(([127, 0, 0, 1], port)))
        .map(drop)
        .map_err(|_| {
            format!(
                "Port {port} is already in use. Close the application using it, then restart the Kuractus {service}."
            )
        })
}

fn docker_compose_start_error(detail: &str) -> String {
    let normalized = detail.to_ascii_lowercase();
    if normalized.contains("15432")
        && (normalized.contains("bind")
            || normalized.contains("address already in use")
            || normalized.contains("already allocated"))
    {
        return "Port 15432 is already in use. Close the local database using that port, then restart Kuractus Desktop.".into();
    }
    detail.to_owned()
}

fn is_supported_global_shortcut(shortcut: &str) -> bool {
    matches!(
        shortcut,
        "CommandOrControl+Alt+A" | "CommandOrControl+Shift+A" | "none"
    )
}

#[cfg(windows)]
fn create_kill_on_close_job(child: &Child) -> Result<std::os::windows::io::OwnedHandle, String> {
    use std::mem::{size_of, zeroed};
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err("Could not create the Kuractus runtime process supervisor.".into());
        }

        let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const std::ffi::c_void,
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if configured == 0 || AssignProcessToJobObject(job, child.as_raw_handle()) == 0 {
            let _ = CloseHandle(job);
            return Err(
                "Could not attach the Kuractus API to its Windows process supervisor. Restart Kuractus Desktop and check Windows process restrictions.".into(),
            );
        }
        Ok(OwnedHandle::from_raw_handle(job))
    }
}

fn wait_until_ready(inner: &Arc<Mutex<RuntimeInner>>) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(120);
    loop {
        {
            let mut state = inner
                .lock()
                .unwrap_or_else(|poisoned| poisoned.into_inner());
            if let Some(child) = state.child.as_mut() {
                if let Ok(Some(exit)) = child.try_wait() {
                    return Err(format!("Kuractus runtime exited before becoming ready (code {}). Check the desktop runtime log.", exit.code().map(|value| value.to_string()).unwrap_or_else(|| "unknown".into())));
                }
            }
        }
        if request_ready().unwrap_or(false) {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(
                "Kuractus did not become ready within two minutes. Check Docker Desktop, then retry."
                    .into(),
            );
        }
        thread::sleep(Duration::from_millis(500));
    }
}

fn request_ready() -> Result<bool, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], API_PORT));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(300))
        .map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_millis(800)))
        .map_err(|error| error.to_string())?;
    stream
        .write_all(b"GET /ready HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    Ok(response.starts_with("HTTP/1.1 200") && response.contains("\"status\":\"ready\""))
}

fn request_identifies_desktop_api() -> Result<bool, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], API_PORT));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(300))
        .map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_millis(800)))
        .map_err(|error| error.to_string())?;
    stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .map_err(|error| error.to_string())?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|error| error.to_string())?;
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return Ok(false);
    };
    if !headers.starts_with("HTTP/1.1 200") && !headers.starts_with("HTTP/1.0 200") {
        return Ok(false);
    }
    let Ok(payload) = serde_json::from_str::<serde_json::Value>(body) else {
        return Ok(false);
    };
    Ok(payload
        .get("desktop_mode")
        .and_then(serde_json::Value::as_bool)
        == Some(true))
}

fn post_shutdown(token: &str) -> Result<(), String> {
    if token.is_empty() || !request_identifies_desktop_api()? {
        return Ok(());
    }
    let address = SocketAddr::from(([127, 0, 0, 1], API_PORT));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_secs(1))
        .map_err(|error| error.to_string())?;
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|error| error.to_string())?;
    let request = format!(
        "POST /v1/internal/desktop/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn desktop_status(
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let runtime = runtime.inner().clone();
    let snapshot = runtime.snapshot();
    if matches!(snapshot.phase, RuntimePhase::Stopped) {
        runtime.apply_preferences(DesktopRuntime::load_preferences(&app));
        return Ok(runtime.snapshot());
    }
    tauri::async_runtime::spawn_blocking(move || {
        runtime.refresh_health();
        runtime.snapshot()
    })
    .await
    .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn desktop_api_token(runtime: State<'_, DesktopRuntime>) -> Result<String, String> {
    runtime.api_token()
}

#[tauri::command]
pub async fn desktop_start(
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.start(&app))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn desktop_restart(
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.restart(&app))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn desktop_stop(
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || runtime.stop(&app))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn desktop_save_preferences(
    provider: String,
    base_url: String,
    model: String,
    close_to_tray: bool,
    autostart: bool,
    notifications: bool,
    global_shortcut: String,
    provider_api_key: Option<String>,
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    if !matches!(provider.as_str(), "unconfigured" | "mock" | "openai") {
        return Err(
            "Choose Not configured, Mock offline demo, or OpenAI-compatible routing.".into(),
        );
    }
    if !is_supported_global_shortcut(&global_shortcut) {
        return Err("Choose one of the supported Kuractus shortcuts.".into());
    }
    if provider == "openai" && model.trim().is_empty() {
        return Err(
            "Enter a model name reported by your selected OpenAI-compatible endpoint.".into(),
        );
    }
    if model.len() > 200 {
        return Err("Model name must contain at most 200 characters.".into());
    }
    if provider == "openai" && !base_url.starts_with("http://") && !base_url.starts_with("https://")
    {
        return Err("Model endpoint must use HTTP or HTTPS.".into());
    }
    if provider == "openai"
        && (base_url.contains('@') || base_url.contains('#') || base_url.len() > 1000)
    {
        return Err("Model endpoint URL is invalid.".into());
    }
    let (base_url, model) = if provider == "mock" {
        (String::new(), "mock-default".to_owned())
    } else if provider == "unconfigured" {
        (String::new(), String::new())
    } else {
        (base_url, model)
    };
    let runtime = runtime.inner().clone();
    let mut preferences = runtime.settings();
    preferences.provider = provider.clone();
    preferences.base_url = base_url.clone();
    preferences.model = model.clone();
    preferences.close_to_tray = close_to_tray;
    preferences.autostart = autostart;
    preferences.notifications = notifications;
    preferences.global_shortcut = global_shortcut;
    if provider == "openai" {
        let connection_id = preferences
            .active_provider_connection_id
            .clone()
            .unwrap_or_else(|| "legacy".into());
        preferences.active_provider_connection_id = Some(connection_id.clone());
        if let Some(connection) = preferences
            .provider_connections
            .iter_mut()
            .find(|connection| connection.id == connection_id)
        {
            connection.base_url = base_url;
            connection.model = model;
        } else {
            preferences.provider_connections.push(ProviderConnection {
                id: connection_id,
                name: "OpenAI-compatible API".into(),
                base_url,
                model,
            });
        }
    }
    if let Some(key) = provider_api_key.filter(|value| !value.is_empty()) {
        if key.len() > 4096 {
            return Err("Provider API key is too long.".into());
        }
        let secret_key = DesktopRuntime::provider_secret_key(
            preferences.active_provider_connection_id.as_deref(),
        );
        DesktopRuntime::entry(&secret_key)?
            .set_password(&key)
            .map_err(|error| {
                format!("Could not store the provider key in Windows Credential Manager: {error}")
            })?;
    }
    DesktopRuntime::save_preferences(&app, &preferences)?;
    runtime.apply_preferences(preferences);
    let _ = runtime.stop(&app);
    runtime.start(&app)
}

#[tauri::command]
pub async fn desktop_save_provider_connection(
    connection_id: String,
    name: String,
    base_url: String,
    model: String,
    provider_api_key: Option<String>,
    activate: bool,
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let id = connection_id.trim();
    let name = name.trim();
    let base_url = base_url.trim();
    let model = model.trim();
    if id.is_empty()
        || id.len() > 64
        || !id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
    {
        return Err("API connection ID is invalid. Please add the connection again.".into());
    }
    if name.is_empty() || name.len() > 80 {
        return Err("Give this API connection a name of 1–80 characters.".into());
    }
    if model.is_empty() || model.len() > 200 {
        return Err("Enter the exact model ID reported by this endpoint.".into());
    }
    if (!base_url.starts_with("http://") && !base_url.starts_with("https://"))
        || base_url.contains('@')
        || base_url.contains('#')
        || base_url.len() > 1000
    {
        return Err("Enter a valid HTTP or HTTPS API endpoint URL.".into());
    }
    if provider_api_key
        .as_ref()
        .is_some_and(|key| key.len() > 4096)
    {
        return Err("Provider API key is too long.".into());
    }

    let runtime = runtime.inner().clone();
    let mut preferences = runtime.settings();
    let connection = ProviderConnection {
        id: id.to_owned(),
        name: name.to_owned(),
        base_url: base_url.to_owned(),
        model: model.to_owned(),
    };
    if let Some(existing) = preferences
        .provider_connections
        .iter_mut()
        .find(|item| item.id == id)
    {
        *existing = connection;
    } else {
        preferences.provider_connections.push(connection);
    }
    if let Some(key) = provider_api_key.filter(|key| !key.is_empty()) {
        let secret_key = DesktopRuntime::provider_secret_key(Some(id));
        DesktopRuntime::entry(&secret_key)?
            .set_password(&key)
            .map_err(|error| {
                format!("Could not store this API key in Windows Credential Manager: {error}")
            })?;
    }
    if activate {
        preferences.provider = "openai".into();
        preferences.base_url = base_url.to_owned();
        preferences.model = model.to_owned();
        preferences.active_provider_connection_id = Some(id.to_owned());
    }
    DesktopRuntime::save_preferences(&app, &preferences)?;
    runtime.apply_preferences(preferences);
    if activate {
        tauri::async_runtime::spawn_blocking(move || runtime.restart(&app))
            .await
            .map_err(|error| error.to_string())?
    } else {
        Ok(runtime.snapshot())
    }
}

#[tauri::command]
pub async fn desktop_forget_provider_key(
    connection_id: String,
    runtime: State<'_, DesktopRuntime>,
) -> Result<RuntimeSnapshot, String> {
    if connection_id.is_empty()
        || connection_id.len() > 64
        || !connection_id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
    {
        return Err("API connection ID is invalid.".into());
    }
    let secret_key = DesktopRuntime::provider_secret_key(Some(&connection_id));
    if let Ok(entry) = DesktopRuntime::entry(&secret_key) {
        let _ = entry.delete_credential();
    }
    Ok(runtime.snapshot())
}

#[tauri::command]
pub async fn desktop_set_close_to_tray(
    enabled: bool,
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let runtime = runtime.inner().clone();
    let mut preferences = runtime.settings();
    preferences.close_to_tray = enabled;
    DesktopRuntime::save_preferences(&app, &preferences)?;
    runtime.apply_preferences(preferences);
    Ok(runtime.snapshot())
}

async fn choose_backup_path(app: &AppHandle, save: bool) -> Result<Option<PathBuf>, String> {
    let (sender, receiver) = std::sync::mpsc::channel();
    let dialog = app
        .dialog()
        .file()
        .add_filter("Kuractus Desktop backup", &["aurabackup"]);
    if save {
        dialog
            .set_file_name("aura-backup.aurabackup")
            .save_file(move |path| {
                let _ = sender.send(path);
            });
    } else {
        dialog.pick_file(move |path| {
            let _ = sender.send(path);
        });
    }
    let picked = tauri::async_runtime::spawn_blocking(move || {
        receiver.recv().map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())??;
    picked
        .map(|path| path.into_path().map_err(|error| error.to_string()))
        .transpose()
}

#[tauri::command]
pub async fn desktop_create_backup(
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    if !matches!(runtime.snapshot().phase, RuntimePhase::Ready) {
        return Err("Start the Kuractus runtime before creating a backup.".into());
    }
    let Some(path) = choose_backup_path(&app, true).await? else {
        return Ok(runtime.snapshot());
    };
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        runtime.stop(&app)?;
        let backup_result = DesktopRuntime::start_postgres_for_maintenance(&app)
            .and_then(|()| runtime.run_sidecar_operation(&app, "--desktop-backup", &path));
        let pause_result = DesktopRuntime::stop_postgres_after_maintenance(&app);
        let resume_result = runtime.start(&app);
        if let Err(error) = backup_result {
            return Err(match resume_result { Ok(_) => error, Err(restart) => format!("{error} Kuractus runtime could not restart: {restart}") });
        }
        if let Err(error) = pause_result {
            let _ = resume_result;
            return Err(format!("Backup completed, but PostgreSQL could not be paused cleanly: {error}"));
        }
        resume_result.map(|snapshot| { runtime.log("Encrypted local credentials were excluded from the backup; app data and database were preserved."); snapshot })
    }).await.map_err(|error| error.to_string())?
}

#[tauri::command]
pub async fn desktop_restore_backup(
    runtime: State<'_, DesktopRuntime>,
    app: AppHandle,
) -> Result<RuntimeSnapshot, String> {
    let Some(path) = choose_backup_path(&app, false).await? else {
        return Ok(runtime.snapshot());
    };
    let runtime = runtime.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        runtime.stop(&app)?;
        let restore_result = DesktopRuntime::start_postgres_for_maintenance(&app)
            .and_then(|()| runtime.run_sidecar_operation(&app, "--desktop-restore", &path));
        if let Err(error) = DesktopRuntime::stop_postgres_after_maintenance(&app) {
            runtime.log(format!("Restore database pause warning: {error}"));
        }
        let restart_result = runtime.start(&app);
        match restore_result {
            Ok(_) => restart_result,
            Err(error) => match restart_result {
                Ok(_) => Err(error),
                Err(restart) => Err(format!(
                    "{error} Kuractus runtime could not restart: {restart}"
                )),
            },
        }
    })
    .await
    .map_err(|error| error.to_string())?
}

#[cfg(test)]
mod tests {
    use super::{
        docker_compose_start_error, ensure_loopback_port_available, is_supported_global_shortcut,
        DesktopPreferences, DesktopRuntime,
    };
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Barrier};
    use std::thread;
    use std::time::Duration;

    #[test]
    fn concurrent_api_token_requests_share_one_credential() {
        const THREADS: usize = 8;
        let runtime = DesktopRuntime::default();
        let barrier = Arc::new(Barrier::new(THREADS));
        let loads = Arc::new(AtomicUsize::new(0));
        let workers = (0..THREADS)
            .map(|_| {
                let runtime = runtime.clone();
                let barrier = barrier.clone();
                let loads = loads.clone();
                thread::spawn(move || {
                    barrier.wait();
                    runtime
                        .api_token_with(|| {
                            loads.fetch_add(1, Ordering::SeqCst);
                            thread::sleep(Duration::from_millis(10));
                            Ok("shared-api-token".to_owned())
                        })
                        .unwrap()
                })
            })
            .collect::<Vec<_>>();
        let tokens = workers
            .into_iter()
            .map(|worker| worker.join().unwrap())
            .collect::<Vec<_>>();

        assert_eq!(loads.load(Ordering::SeqCst), 1);
        assert!(tokens.iter().all(|token| token == "shared-api-token"));
    }

    #[test]
    fn reports_loopback_port_conflicts_with_the_exact_port() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let error = ensure_loopback_port_available(port, "Kuractus API").unwrap_err();
        assert!(error.contains(&port.to_string()));
        assert!(error.contains("already in use"));
    }

    #[test]
    fn turns_postgres_bind_errors_into_user_actionable_diagnostics() {
        let error = docker_compose_start_error(
            "failed to bind host port 127.0.0.1:15432: address already in use",
        );
        assert!(error.contains("Port 15432 is already in use"));
        assert!(error.contains("Close the local database"));
    }

    #[test]
    fn accepts_only_allowlisted_shortcut_values_including_disabled() {
        assert!(is_supported_global_shortcut("CommandOrControl+Alt+A"));
        assert!(is_supported_global_shortcut("CommandOrControl+Shift+A"));
        assert!(is_supported_global_shortcut("none"));
        assert!(!is_supported_global_shortcut("Alt+F4"));
    }

    #[test]
    fn new_desktop_preferences_do_not_assume_a_provider_or_model() {
        let preferences = DesktopPreferences::default();

        assert_eq!(preferences.provider, "unconfigured");
        assert!(preferences.base_url.is_empty());
        assert!(preferences.model.is_empty());
    }
}
