use base64::Engine;
use serde::{Deserialize, Serialize};
use std::collections::{HashSet, VecDeque};
use std::fs::{self, OpenOptions};
use std::io::Read;
use std::path::{Component, Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, State};
use tauri_plugin_dialog::DialogExt;
use uuid::Uuid;

use crate::runtime::DesktopRuntime;

const MAX_INDEXED_FILES: usize = 5_000;
const MAX_VISITED_ENTRIES: usize = 10_000;
const MAX_DEPTH: usize = 24;
const MAX_OPEN_BYTES: u64 = 25 * 1024 * 1024;
const MAX_DIRECTORY_ENTRIES: usize = 2_000;
const MAX_DROPPED_FILES: usize = 5;
const MAX_DROPPED_TOTAL_BYTES: u64 = 40 * 1024 * 1024;
const MAX_PENDING_DROP_BATCHES: usize = 8;

#[derive(Default)]
pub struct PendingDesktopDrop(Mutex<VecDeque<Vec<PathBuf>>>);

impl PendingDesktopDrop {
    pub fn capture(&self, paths: Vec<PathBuf>) -> Result<(), String> {
        if paths.is_empty() {
            return Ok(());
        }
        let mut batches = self
            .0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if batches.len() >= MAX_PENDING_DROP_BATCHES {
            return Err(
                "AURA is still processing earlier dropped files. Try again in a moment.".into(),
            );
        }
        batches.push_back(paths);
        Ok(())
    }

    fn take(&self) -> Option<Vec<PathBuf>> {
        self.0
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
            .pop_front()
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DirectoryConnection {
    id: String,
    name: String,
    created_at: u128,
    updated_at: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct IndexedFolderFile {
    connection_id: String,
    connection_name: String,
    relative_path: String,
    name: String,
    size: u64,
    last_modified: u128,
    mime_type: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredConnection {
    connection: DirectoryConnection,
    path: PathBuf,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StoredIndex {
    connection_id: String,
    indexed_at: u128,
    truncated: bool,
    files: Vec<IndexedFolderFile>,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DirectoryIndexSnapshot {
    indexed_at: u128,
    file_count: usize,
    truncated: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DirectoryBrowseEntry {
    name: String,
    kind: String,
    relative_path: String,
    size: u64,
    mime_type: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DirectoryBrowseSnapshot {
    relative_path: String,
    entries: Vec<DirectoryBrowseEntry>,
    truncated: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OpenedFolderFile {
    name: String,
    mime_type: String,
    bytes_base64: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct OpenedDesktopDrop {
    name: String,
    mime_type: String,
    bytes_base64: String,
}

fn state_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let path = DesktopRuntime::aura_config_dir(app)?.join("folder-access");
    fs::create_dir_all(&path)
        .map_err(|error| format!("Could not prepare folder connection settings: {error}"))?;
    Ok(path)
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let temporary = path.with_extension("json.tmp");
    let bytes = serde_json::to_vec_pretty(value).map_err(|error| error.to_string())?;
    fs::write(&temporary, bytes).map_err(|error| error.to_string())?;
    fs::rename(temporary, path).map_err(|error| error.to_string())
}

fn connections_file(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(state_dir(app)?.join("connections.json"))
}
fn indexes_file(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(state_dir(app)?.join("indexes.json"))
}

fn load_connections(app: &AppHandle) -> Result<Vec<StoredConnection>, String> {
    match fs::read(connections_file(app)?) {
        Ok(bytes) => serde_json::from_slice(&bytes)
            .map_err(|error| format!("Folder connection data is invalid: {error}")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(error) => Err(error.to_string()),
    }
}

fn load_indexes(app: &AppHandle) -> Result<Vec<StoredIndex>, String> {
    match fs::read(indexes_file(app)?) {
        Ok(bytes) => serde_json::from_slice(&bytes)
            .map_err(|error| format!("Folder index data is invalid: {error}")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Vec::new()),
        Err(error) => Err(error.to_string()),
    }
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn safe_relative_path(value: &str) -> Result<PathBuf, String> {
    let path = Path::new(value);
    if path.as_os_str().is_empty()
        || value.contains(['\\', ':'])
        || value
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
        || path
            .components()
            .any(|part| !matches!(part, Component::Normal(_)))
    {
        return Err("Indexed file path is invalid.".into());
    }
    Ok(path.to_path_buf())
}

#[tauri::command]
pub async fn desktop_pick_folder(app: AppHandle) -> Result<Option<DirectoryConnection>, String> {
    let (sender, receiver) = std::sync::mpsc::channel();
    app.dialog().file().pick_folder(move |path| {
        let _ = sender.send(path);
    });
    let picked = tauri::async_runtime::spawn_blocking(move || {
        receiver.recv().map_err(|error| error.to_string())
    })
    .await
    .map_err(|error| error.to_string())??;
    let Some(path) = picked else { return Ok(None) };
    let path = path.into_path().map_err(|error| error.to_string())?;
    let root = path
        .canonicalize()
        .map_err(|error| format!("Could not connect the selected folder: {error}"))?;
    if !root.is_dir() {
        return Err("Choose a folder to connect.".into());
    }
    let mut records = load_connections(&app)?;
    if let Some(record) = records.iter_mut().find(|record| record.path == root) {
        record.connection.updated_at = now_ms();
        let connection = record.connection.clone();
        write_json(&connections_file(&app)?, &records)?;
        return Ok(Some(connection));
    }
    let name = root
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("Folder")
        .to_owned();
    let now = now_ms();
    let connection = DirectoryConnection {
        id: format!("native-{}", Uuid::new_v4()),
        name,
        created_at: now,
        updated_at: now,
    };
    records.push(StoredConnection {
        connection: connection.clone(),
        path: root,
    });
    write_json(&connections_file(&app)?, &records)?;
    Ok(Some(connection))
}

#[tauri::command]
pub async fn desktop_list_folders(app: AppHandle) -> Result<Vec<DirectoryConnection>, String> {
    Ok(load_connections(&app)?
        .into_iter()
        .map(|record| record.connection)
        .collect())
}

#[tauri::command]
pub async fn desktop_remove_folder(connection_id: String, app: AppHandle) -> Result<(), String> {
    let mut connections = load_connections(&app)?;
    let old_len = connections.len();
    connections.retain(|record| record.connection.id != connection_id);
    if old_len == connections.len() {
        return Err("Connected folder was not found.".into());
    }
    let mut indexes = load_indexes(&app)?;
    indexes.retain(|index| index.connection_id != connection_id);
    write_json(&connections_file(&app)?, &connections)?;
    write_json(&indexes_file(&app)?, &indexes)?;
    Ok(())
}

fn is_reparse_or_symlink(path: &Path) -> bool {
    let Ok(metadata) = fs::symlink_metadata(path) else {
        return true;
    };
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        return metadata.file_attributes() & 0x400 != 0;
    }
    #[cfg(not(windows))]
    {
        false
    }
}

fn is_reparse_metadata(metadata: &std::fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        return metadata.file_attributes() & 0x400 != 0;
    }
    #[cfg(not(windows))]
    {
        false
    }
}

fn read_dropped_files(paths: Vec<PathBuf>) -> Result<Vec<OpenedDesktopDrop>, String> {
    if paths.len() > MAX_DROPPED_FILES {
        return Err(format!("Drop at most {MAX_DROPPED_FILES} files at a time."));
    }

    let mut total_bytes = 0u64;
    let mut opened = Vec::with_capacity(paths.len());
    for path in paths {
        if is_reparse_or_symlink(&path) {
            return Err("AURA cannot import symbolic links or Windows junctions.".into());
        }
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            // Inspect the final path component itself instead of following a
            // symlink/junction if it changes between validation and open.
            options.custom_flags(0x00200000); // FILE_FLAG_OPEN_REPARSE_POINT
        }
        let mut file = options
            .open(&path)
            .map_err(|_| "A dropped file is no longer available.".to_string())?;
        let metadata = file
            .metadata()
            .map_err(|_| "Could not inspect a dropped file.".to_string())?;
        if is_reparse_metadata(&metadata) {
            return Err("AURA cannot import symbolic links or Windows junctions.".into());
        }
        if !metadata.is_file() {
            return Err("Drop files only; folders are not imported.".into());
        }
        if metadata.len() > MAX_OPEN_BYTES {
            return Err("Each dropped file must be 25 MB or smaller.".into());
        }
        total_bytes = total_bytes
            .checked_add(metadata.len())
            .ok_or_else(|| "The dropped files exceed the 40 MB total limit.".to_string())?;
        if total_bytes > MAX_DROPPED_TOTAL_BYTES {
            return Err("The dropped files exceed the 40 MB total limit.".into());
        }

        let mut bytes = Vec::with_capacity(metadata.len() as usize);
        file.by_ref()
            .take(MAX_OPEN_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "Could not read a dropped file.".to_string())?;
        if bytes.len() as u64 > MAX_OPEN_BYTES {
            return Err("A dropped file grew beyond the 25 MB import limit.".into());
        }
        total_bytes = total_bytes
            .checked_sub(metadata.len())
            .and_then(|value| value.checked_add(bytes.len() as u64))
            .ok_or_else(|| "The dropped files exceed the 40 MB total limit.".to_string())?;
        if total_bytes > MAX_DROPPED_TOTAL_BYTES {
            return Err("The dropped files exceed the 40 MB total limit.".into());
        }

        let name = path
            .file_name()
            .and_then(|value| value.to_str())
            .unwrap_or("File")
            .to_owned();
        opened.push(OpenedDesktopDrop {
            mime_type: mime_type(&path),
            name,
            bytes_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
        });
    }
    Ok(opened)
}

#[tauri::command]
pub async fn desktop_consume_dropped_files(
    pending: State<'_, PendingDesktopDrop>,
) -> Result<Vec<OpenedDesktopDrop>, String> {
    let Some(paths) = pending.take() else {
        return Ok(Vec::new());
    };
    tauri::async_runtime::spawn_blocking(move || read_dropped_files(paths))
        .await
        .map_err(|_| "Could not process the dropped files.".to_string())?
}

fn mime_type(path: &Path) -> String {
    match path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "txt" | "md" | "rst" | "log" => "text/plain",
        "html" | "htm" => "text/html",
        "pdf" => "application/pdf",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "json" => "application/json",
        "csv" => "text/csv",
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _ => "application/octet-stream",
    }
    .to_owned()
}

fn connection_root(app: &AppHandle, id: &str) -> Result<(DirectoryConnection, PathBuf), String> {
    let record = load_connections(app)?
        .into_iter()
        .find(|record| record.connection.id == id)
        .ok_or_else(|| "Connected folder is unavailable. Reconnect it from Library.".to_string())?;
    let root = record
        .path
        .canonicalize()
        .map_err(|_| "Connected folder is unavailable. Reconnect it from Library.".to_string())?;
    Ok((record.connection, root))
}

fn resolve_connection_directory(root: &Path, relative_path: &str) -> Result<PathBuf, String> {
    if relative_path.is_empty() {
        return Ok(root.to_path_buf());
    }
    let relative = safe_relative_path(relative_path)?;
    let mut candidate = root.to_path_buf();
    for component in relative.components() {
        let Component::Normal(segment) = component else {
            return Err("Connected-folder path is invalid.".into());
        };
        candidate.push(segment);
        if is_reparse_or_symlink(&candidate) {
            return Err("AURA cannot browse symbolic links or Windows junctions.".into());
        }
    }
    let canonical = candidate
        .canonicalize()
        .map_err(|_| "This folder is no longer available in the connected folder.".to_string())?;
    if !canonical.starts_with(root) || !canonical.is_dir() {
        return Err("Choose a folder inside the connected folder.".into());
    }
    Ok(canonical)
}

#[tauri::command]
pub async fn desktop_list_folder_entries(
    connection_id: String,
    relative_path: String,
    app: AppHandle,
) -> Result<DirectoryBrowseSnapshot, String> {
    let (connection, root) = connection_root(&app, &connection_id)?;
    let directory = resolve_connection_directory(&root, &relative_path)?;
    let mut entries = Vec::new();
    let mut truncated = false;
    for entry in
        fs::read_dir(&directory).map_err(|_| "Could not read this connected folder.".to_string())?
    {
        let entry = match entry {
            Ok(entry) => entry,
            Err(_) => continue,
        };
        if entries.len() >= MAX_DIRECTORY_ENTRIES {
            truncated = true;
            break;
        }
        let path = entry.path();
        if is_reparse_or_symlink(&path) {
            continue;
        }
        let metadata = match fs::symlink_metadata(&path) {
            Ok(metadata) if !is_reparse_metadata(&metadata) => metadata,
            _ => continue,
        };
        let kind = if metadata.is_dir() {
            "directory"
        } else if metadata.is_file() {
            "file"
        } else {
            continue;
        };
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
            continue;
        };
        let relative = if relative_path.is_empty() {
            name.to_owned()
        } else {
            format!("{relative_path}/{name}")
        };
        entries.push(DirectoryBrowseEntry {
            name: name.to_owned(),
            kind: kind.to_owned(),
            relative_path: relative,
            size: metadata.len(),
            mime_type: mime_type(&path),
        });
    }
    entries.sort_by(|left, right| {
        (left.kind != "directory")
            .cmp(&(right.kind != "directory"))
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    let _ = connection;
    Ok(DirectoryBrowseSnapshot {
        relative_path,
        entries,
        truncated,
    })
}

fn enumerate_files(
    connection: &DirectoryConnection,
    root: &Path,
) -> Result<(Vec<IndexedFolderFile>, bool), String> {
    let mut pending = VecDeque::from([(root.to_path_buf(), 0usize)]);
    let mut visited = HashSet::new();
    let mut files = Vec::new();
    let mut entry_count = 0usize;
    let mut truncated = false;
    while let Some((directory, depth)) = pending.pop_front() {
        let canonical = match directory.canonicalize() {
            Ok(path) => path,
            Err(_) => continue,
        };
        if !canonical.starts_with(root) || !visited.insert(canonical.clone()) {
            continue;
        }
        let entries = fs::read_dir(&canonical)
            .map_err(|error| format!("Could not read connected folder: {error}"))?;
        for entry in entries {
            let entry = match entry {
                Ok(entry) => entry,
                Err(_) => continue,
            };
            entry_count += 1;
            if entry_count > MAX_VISITED_ENTRIES {
                truncated = true;
                break;
            }
            let path = entry.path();
            if is_reparse_or_symlink(&path) {
                continue;
            }
            let metadata = match fs::metadata(&path) {
                Ok(metadata) => metadata,
                Err(_) => continue,
            };
            if metadata.is_dir() {
                if depth < MAX_DEPTH {
                    pending.push_back((path, depth + 1));
                } else {
                    truncated = true;
                }
                continue;
            }
            if !metadata.is_file() {
                continue;
            }
            if files.len() >= MAX_INDEXED_FILES {
                truncated = true;
                break;
            }
            let canonical_file = match path.canonicalize() {
                Ok(value) if value.starts_with(root) => value,
                _ => continue,
            };
            let relative = canonical_file
                .strip_prefix(root)
                .map_err(|_| "Connected-folder path escaped its root.".to_string())?;
            let relative_path = relative.to_string_lossy().replace('\\', "/");
            let name = canonical_file
                .file_name()
                .and_then(|value| value.to_str())
                .unwrap_or("File")
                .to_owned();
            let modified = metadata
                .modified()
                .ok()
                .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
                .map(|duration| duration.as_millis())
                .unwrap_or_default();
            files.push(IndexedFolderFile {
                connection_id: connection.id.clone(),
                connection_name: connection.name.clone(),
                relative_path,
                name,
                size: metadata.len(),
                last_modified: modified,
                mime_type: mime_type(&canonical_file),
            });
        }
        if truncated {
            break;
        }
    }
    files.sort_by(|left, right| {
        left.relative_path
            .to_lowercase()
            .cmp(&right.relative_path.to_lowercase())
    });
    Ok((files, truncated))
}

#[tauri::command]
pub async fn desktop_index_folder(
    connection_id: String,
    app: AppHandle,
) -> Result<DirectoryIndexSnapshot, String> {
    let (connection, root) = connection_root(&app, &connection_id)?;
    let (files, truncated) = enumerate_files(&connection, &root)?;
    let indexed_at = now_ms();
    let snapshot = StoredIndex {
        connection_id: connection_id.clone(),
        indexed_at,
        truncated,
        files,
    };
    let mut indexes = load_indexes(&app)?;
    indexes.retain(|index| index.connection_id != connection_id);
    indexes.push(snapshot.clone());
    write_json(&indexes_file(&app)?, &indexes)?;
    Ok(DirectoryIndexSnapshot {
        indexed_at,
        file_count: snapshot.files.len(),
        truncated,
    })
}

#[tauri::command]
pub async fn desktop_get_folder_index_snapshot(
    connection_id: String,
    app: AppHandle,
) -> Result<Option<DirectoryIndexSnapshot>, String> {
    Ok(load_indexes(&app)?
        .into_iter()
        .find(|index| index.connection_id == connection_id)
        .map(|index| DirectoryIndexSnapshot {
            indexed_at: index.indexed_at,
            file_count: index.files.len(),
            truncated: index.truncated,
        }))
}

#[tauri::command]
pub async fn desktop_search_folder_indexes(
    query: String,
    limit: Option<usize>,
    app: AppHandle,
) -> Result<Vec<IndexedFolderFile>, String> {
    let query = query.trim().to_lowercase();
    if query.is_empty() {
        return Ok(Vec::new());
    }
    let maximum = limit.unwrap_or(25).clamp(1, 50);
    let mut matches = Vec::new();
    for index in load_indexes(&app)? {
        for file in index.files {
            let haystack = format!(
                "{} {} {}",
                file.name, file.relative_path, file.connection_name
            )
            .to_lowercase();
            if haystack.contains(&query) {
                matches.push(file);
            }
        }
    }
    matches.truncate(maximum);
    Ok(matches)
}

#[tauri::command]
pub async fn desktop_read_folder_file(
    connection_id: String,
    relative_path: String,
    app: AppHandle,
    _runtime: State<'_, DesktopRuntime>,
) -> Result<OpenedFolderFile, String> {
    let (connection, root) = connection_root(&app, &connection_id)?;
    let requested = safe_relative_path(&relative_path)?;
    let candidate = root.join(requested);
    if is_reparse_or_symlink(&candidate) {
        return Err(
            "AURA cannot read symbolic links or Windows junctions from connected folders.".into(),
        );
    }
    let canonical = candidate
        .canonicalize()
        .map_err(|_| "This file is no longer available in the connected folder.".to_string())?;
    if !canonical.starts_with(&root) {
        return Err("Connected-folder file escaped its selected root.".into());
    }
    let metadata = fs::metadata(&canonical).map_err(|error| error.to_string())?;
    if !metadata.is_file() {
        return Err("Choose a file inside the connected folder.".into());
    }
    if metadata.len() > MAX_OPEN_BYTES {
        return Err("This file exceeds the 25 MB connected-folder open limit.".into());
    }
    let bytes =
        fs::read(&canonical).map_err(|error| format!("Could not open this file: {error}"))?;
    let name = canonical
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("File")
        .to_owned();
    let _ = connection;
    Ok(OpenedFolderFile {
        mime_type: mime_type(&canonical),
        name,
        bytes_base64: base64::engine::general_purpose::STANDARD.encode(bytes),
    })
}

#[cfg(test)]
mod tests {
    use super::{
        read_dropped_files, resolve_connection_directory, safe_relative_path, MAX_DROPPED_FILES,
    };
    use std::fs;
    use std::path::PathBuf;
    use uuid::Uuid;

    #[test]
    fn accepts_nested_indexed_paths() {
        assert_eq!(
            safe_relative_path("papers/2026/report.pdf").unwrap(),
            PathBuf::from("papers/2026/report.pdf")
        );
    }

    #[test]
    fn rejects_empty_traversal_and_absolute_paths() {
        for value in [
            "",
            "../secret.txt",
            "papers/../../secret.txt",
            "C:\\Users\\Minh\\secret.txt",
            "\\\\server\\share\\file.txt",
            "/etc/passwd",
        ] {
            assert!(
                safe_relative_path(value).is_err(),
                "accepted unsafe path {value:?}"
            );
        }
    }

    #[test]
    fn reads_small_explicitly_dropped_files_with_name_and_mime() {
        let path = std::env::temp_dir().join(format!("aura-drop-{}.txt", Uuid::new_v4()));
        let expected_name = path.file_name().unwrap().to_string_lossy().into_owned();
        fs::write(&path, b"hello").unwrap();
        let result = read_dropped_files(vec![path.clone()]).unwrap();
        fs::remove_file(path).unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].name, expected_name);
        assert_eq!(result[0].mime_type, "text/plain");
        assert_eq!(result[0].bytes_base64, "aGVsbG8=");
    }

    #[test]
    fn rejects_too_many_dropped_files_before_opening_them() {
        let paths = (0..=MAX_DROPPED_FILES)
            .map(|index| PathBuf::from(format!("missing-{index}.txt")))
            .collect();
        assert!(read_dropped_files(paths)
            .unwrap_err()
            .contains("Drop at most"));
    }

    #[test]
    fn resolves_only_directories_within_the_selected_folder() {
        let root = std::env::temp_dir().join(format!("aura-folder-{}", Uuid::new_v4()));
        fs::create_dir_all(root.join("papers")).unwrap();
        let canonical_root = root.canonicalize().unwrap();
        assert_eq!(
            resolve_connection_directory(&canonical_root, "papers").unwrap(),
            canonical_root.join("papers")
        );
        assert!(resolve_connection_directory(&canonical_root, "../outside").is_err());
        assert!(resolve_connection_directory(&canonical_root, "missing").is_err());
        fs::remove_dir_all(root).unwrap();
    }
}
