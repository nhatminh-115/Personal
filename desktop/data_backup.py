"""Local backup/restore routines for the Windows desktop sidecar."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

FORMAT_VERSION = 1
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024 * 1024
MAX_DUMP_BYTES = 10 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
ALLOWED_ROOTS = {"database", "workspace", "checkpoints", "config"}


def _desktop_path(variable: str) -> Path:
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError(f"Desktop data location {variable} is not configured.")
    return Path(value)


def _compose_prefix() -> list[str]:
    compose = _desktop_path("AURA_DESKTOP_COMPOSE_FILE")
    if not compose.is_file():
        raise RuntimeError("Kuractus Desktop's Compose runtime definition is unavailable.")
    if not os.environ.get("AURA_DESKTOP_POSTGRES_PASSWORD"):
        raise RuntimeError("Kuractus Desktop database credential is unavailable.")
    return ["docker", "compose", "--project-name", "aura-desktop", "--file", str(compose), "exec", "-T", "postgres"]


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_attribute)


def _add_directory(archive: zipfile.ZipFile, source: Path, archive_prefix: str) -> None:
    if not source.exists():
        return
    for root, directory_names, file_names in os.walk(source, followlinks=False):
        root_path = Path(root)
        directory_names[:] = [name for name in directory_names if not _is_reparse_or_symlink(root_path / name)]
        for name in file_names:
            path = root_path / name
            if _is_reparse_or_symlink(path) or not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            archive.write(path, f"{archive_prefix}/{relative}", compress_type=zipfile.ZIP_STORED)


def create_backup(destination: Path) -> dict[str, object]:
    destination = destination.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    workspace = _desktop_path("AURA_WORKSPACE_ROOT")
    checkpoint = _desktop_path("CHECKPOINT_DB_PATH")
    checkpoint_root = checkpoint.parent
    configuration = _desktop_path("AURA_DESKTOP_CONFIG_DIR")
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    dump_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="aura-postgres-", suffix=".dump", delete=False) as handle:
            dump_file = Path(handle.name)
        command = _compose_prefix() + ["pg_dump", "-U", "aura_desktop", "-d", "aura_desktop", "--format=custom"]
        with dump_file.open("wb") as output:
            result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0 or dump_file.stat().st_size > MAX_DUMP_BYTES:
            raise RuntimeError("PostgreSQL backup failed or exceeded the supported backup size.")

        manifest = {
            "format": "aura-desktop-backup",
            "format_version": FORMAT_VERSION,
            "created_at_unix_ms": int(time.time() * 1000),
            "includes": ["postgresql_pgvector", "workspace_files", "langgraph_checkpoints", "desktop_preferences", "connected_folder_references"],
            "excludes": ["windows_credential_manager_secrets", "external_folder_file_contents"],
        }
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
            archive.write(dump_file, "database/aura.dump", compress_type=zipfile.ZIP_STORED)
            _add_directory(archive, workspace, "workspace")
            _add_directory(archive, checkpoint_root, "checkpoints")
            preferences = configuration / "desktop-preferences.json"
            if preferences.is_file() and not _is_reparse_or_symlink(preferences):
                archive.write(preferences, "config/desktop-preferences.json", compress_type=zipfile.ZIP_STORED)
            folder_access = configuration / "folder-access"
            _add_directory(archive, folder_access, "config/folder-access")
        os.replace(temporary, destination)
        return {"path": str(destination), "size_bytes": destination.stat().st_size, "created_at_unix_ms": manifest["created_at_unix_ms"]}
    finally:
        if dump_file is not None:
            dump_file.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def _checked_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise RuntimeError("Backup contains too many files.")
    total = 0
    has_database = False
    seen_names: set[str] = set()
    for item in members:
        name = item.filename
        is_directory = item.is_dir()
        normalized_name = name[:-1] if is_directory and name.endswith("/") else name
        parts = normalized_name.split("/")
        path = PurePosixPath(normalized_name)
        if not name or "\0" in name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
            raise RuntimeError("Backup contains an unsafe file path.")
        if any(part in {"", ".", ".."} for part in parts):
            raise RuntimeError("Backup contains an unsafe file path.")
        normalized_key = "/".join(parts).casefold()
        if normalized_key in seen_names:
            raise RuntimeError("Backup contains duplicate file paths.")
        seen_names.add(normalized_key)
        if path.parts and path.parts[0] not in ALLOWED_ROOTS | {"manifest.json"}:
            raise RuntimeError("Backup contains an unsupported data section.")
        if path.parts and path.parts[0] == "manifest.json" and name != "manifest.json":
            raise RuntimeError("Backup contains an unsupported manifest path.")
        if path.parts and path.parts[0] == "config" and name not in {
            "config/desktop-preferences.json",
            "config/folder-access/connections.json",
            "config/folder-access/indexes.json",
        }:
            raise RuntimeError("Backup contains an unsupported configuration file.")
        mode = item.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise RuntimeError("Backup contains a symbolic link.")
        if is_directory:
            continue
        if item.compress_type != zipfile.ZIP_STORED:
            raise RuntimeError("Backup uses an unsupported compression method.")
        total += item.file_size
        if total > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Backup exceeds the 20 GB restore limit.")
        if name == "database/aura.dump":
            has_database = True
        elif name.startswith("database/"):
            raise RuntimeError("Backup contains an unexpected database file.")
    if not has_database:
        raise RuntimeError("Backup does not contain a PostgreSQL database dump.")
    if "manifest.json" not in archive.namelist():
        raise RuntimeError("Backup manifest is missing.")
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (json.JSONDecodeError, KeyError, OSError) as error:
        raise RuntimeError("Backup manifest is invalid.") from error
    if manifest.get("format") != "aura-desktop-backup" or manifest.get("format_version") != FORMAT_VERSION:
        raise RuntimeError("This Kuractus Desktop backup format is not supported.")
    return members


def _safe_restore_path(stage: Path, archive_name: str) -> Path:
    relative = PurePosixPath(archive_name)
    destination = stage.joinpath(*relative.parts)
    if not destination.resolve().is_relative_to(stage.resolve()):
        raise RuntimeError("Backup file path escaped restore staging.")
    return destination


def _copy_restore_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for root, directory_names, file_names in os.walk(source, followlinks=False):
        root_path = Path(root)
        directory_names[:] = [name for name in directory_names if not _is_reparse_or_symlink(root_path / name)]
        relative = root_path.relative_to(source)
        target_root = destination / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for name in file_names:
            source_file = root_path / name
            if _is_reparse_or_symlink(source_file) or not source_file.is_file():
                continue
            shutil.copy2(source_file, target_root / name)


def _replace_tree(source: Path, destination: Path, rollback: Path) -> None:
    if not source.exists():
        return
    if destination.exists():
        os.replace(destination, rollback)
    try:
        os.replace(source, destination)
    except OSError:
        if rollback.exists() and not destination.exists():
            os.replace(rollback, destination)
        raise


def restore_backup(source: Path) -> dict[str, object]:
    source = source.expanduser().absolute()
    if not source.is_file():
        raise RuntimeError("Choose an existing Kuractus Desktop backup file.")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            _checked_members(archive)
    except zipfile.BadZipFile as error:
        raise RuntimeError("This file is not a valid Kuractus Desktop backup.") from error
    local_root = _desktop_path("AURA_LOCAL_DATA_DIR")
    workspace = _desktop_path("AURA_WORKSPACE_ROOT")
    checkpoint = _desktop_path("CHECKPOINT_DB_PATH")
    configuration = _desktop_path("AURA_DESKTOP_CONFIG_DIR")
    safety_directory = local_root / "restore-safety"
    safety_directory.mkdir(parents=True, exist_ok=True)
    safety_copy = safety_directory / f"before-restore-{int(time.time())}.aurabackup"
    create_backup(safety_copy)

    stage = local_root / f"restore-staging-{uuid.uuid4().hex}"
    stage.mkdir(parents=True, exist_ok=False)
    rollback_root = local_root / f"restore-rollback-{uuid.uuid4().hex}"
    rollback_root.mkdir(parents=True, exist_ok=False)
    succeeded = False
    try:
        with zipfile.ZipFile(source, "r") as archive:
            members = _checked_members(archive)
            for item in members:
                if item.is_dir() or item.filename == "manifest.json":
                    continue
                target = _safe_restore_path(stage, item.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item, "r") as input_stream, target.open("wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)

        dump_file = stage / "database" / "aura.dump"
        if dump_file.stat().st_size > MAX_DUMP_BYTES:
            raise RuntimeError("Backup PostgreSQL dump exceeds the 10 GB restore limit.")
        restore = _compose_prefix() + ["pg_restore", "--no-owner", "--no-acl", "--clean", "--if-exists", "-U", "aura_desktop", "-d", "aura_desktop"]
        with dump_file.open("rb") as database_input:
            result = subprocess.run(restore, stdin=database_input, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
        if result.returncode != 0:
            raise RuntimeError("PostgreSQL restore failed. The pre-restore safety backup was preserved.")

        _copy_restore_tree(stage / "workspace", rollback_root / "workspace-stage")
        _copy_restore_tree(stage / "checkpoints", rollback_root / "checkpoints-stage")
        _replace_tree(rollback_root / "workspace-stage", workspace, rollback_root / "workspace-before")
        _replace_tree(rollback_root / "checkpoints-stage", checkpoint.parent, rollback_root / "checkpoints-before")

        preferences_source = stage / "config" / "desktop-preferences.json"
        if preferences_source.is_file():
            preferences_destination = configuration / "desktop-preferences.json"
            configuration.mkdir(parents=True, exist_ok=True)
            shutil.copy2(preferences_source, preferences_destination)
        folder_source = stage / "config" / "folder-access"
        if folder_source.is_dir():
            folder_destination = configuration / "folder-access"
            rollback_folder = rollback_root / "folder-access-before"
            if folder_destination.exists():
                os.replace(folder_destination, rollback_folder)
            try:
                shutil.copytree(folder_source, folder_destination)
            except OSError:
                if rollback_folder.exists() and not folder_destination.exists():
                    os.replace(rollback_folder, folder_destination)
                raise
        succeeded = True
        return {"restored": True, "safety_backup": str(safety_copy)}
    except (zipfile.BadZipFile, OSError) as error:
        raise RuntimeError("Backup restore failed. The pre-restore safety backup was preserved.") from error
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        # Keep rollback copies after failure; successful restores already have
        # a portable safety archive and can release the duplicate local data.
        if succeeded:
            shutil.rmtree(rollback_root, ignore_errors=True)
