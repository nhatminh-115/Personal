"""Back up and restore AURA's local SQLite database, checkpoints, and workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.engine import make_url

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import settings
from scripts.backup_compose import _validate_workspace_archive, extract_workspace_archive


DATABASE_FILE = "database.sqlite"
CHECKPOINT_DIRECTORY = "checkpoints"
CHECKPOINT_FILE = "aura_checkpoints.db"
WORKSPACE_FILE = "workspace.tar.gz"
MANIFEST_FILE = "manifest.json"
FORMAT_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _configured_paths() -> tuple[Path, Path, Path]:
    url = make_url(settings.DATABASE_URL)
    if (
        url.drivername not in {"sqlite", "sqlite+aiosqlite"}
        or not url.database
        or url.database == ":memory:"
        or url.database.startswith("file:")
    ):
        raise ValueError("Local backup requires a file-backed SQLite DATABASE_URL")
    database_path = Path(url.database).expanduser()
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    checkpoint_path = Path(settings.CHECKPOINT_DB_PATH).expanduser()
    workspace_path = Path(settings.AURA_WORKSPACE_ROOT).expanduser()
    paths = tuple(path.resolve() for path in (database_path, checkpoint_path, workspace_path))
    if paths[0] == paths[1]:
        raise ValueError("SQLite application database and checkpoint paths must be different")
    if paths[2] in paths[0].parents or paths[2] in paths[1].parents:
        raise ValueError("SQLite database and checkpoint files must be outside the workspace root")
    return paths


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required SQLite store does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_db = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    destination_db = sqlite3.connect(destination)
    try:
        source_db.backup(destination_db)
        destination_db.commit()
    finally:
        destination_db.close()
        source_db.close()


def _archive_workspace(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise NotADirectoryError(f"Workspace directory does not exist: {source}")
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            if path.is_symlink():
                raise ValueError("Local workspace backup does not support symbolic links")
            if path.is_dir() or path.is_file():
                archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
            else:
                raise ValueError("Local workspace contains a non-regular filesystem entry")
    _validate_workspace_archive(destination)


def verify_backup(archive_path: Path) -> dict:
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        allowed = {
            MANIFEST_FILE,
            DATABASE_FILE,
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_FILE}",
            WORKSPACE_FILE,
        }
        by_name = {member.name: member for member in members}
        if len(by_name) != len(members) or set(by_name) != allowed:
            raise ValueError("Local backup contains missing, duplicate, or unexpected files")
        if any(not member.isfile() for member in members):
            raise ValueError("Local backup entries must be regular files")
        manifest_stream = archive.extractfile(by_name[MANIFEST_FILE])
        if manifest_stream is None:
            raise ValueError("Local backup manifest cannot be read")
        manifest = json.load(manifest_stream)
        if not isinstance(manifest, dict) or manifest.get("format_version") != FORMAT_VERSION:
            raise ValueError("Unsupported local AURA backup format")
        payload_names = allowed - {MANIFEST_FILE}
        hashes = manifest.get("files")
        if not isinstance(hashes, dict) or set(hashes) != payload_names:
            raise ValueError("Local backup manifest does not match its data files")
        for name in sorted(payload_names):
            stream = archive.extractfile(by_name[name])
            if stream is None or _sha256_stream(stream) != hashes[name]:
                raise ValueError(f"Local backup checksum failed for {name}")

        workspace_stream = archive.extractfile(by_name[WORKSPACE_FILE])
        if workspace_stream is None:
            raise ValueError("Local workspace snapshot cannot be read")
        with tempfile.TemporaryDirectory(prefix="aura-local-verify-") as temp_name:
            workspace_path = Path(temp_name) / WORKSPACE_FILE
            with workspace_path.open("xb") as output:
                shutil.copyfileobj(workspace_stream, output)
            _validate_workspace_archive(workspace_path)
        return manifest


def create_backup(destination: Path, *, api_stopped: bool = False) -> Path:
    if not api_stopped:
        raise ValueError("Stop the local AURA API first, then pass --api-stopped to confirm both SQLite stores are idle")
    database_path, checkpoint_path, workspace_path = _configured_paths()
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    if any(path == destination or path in destination.parents for path in (database_path, checkpoint_path, workspace_path)):
        raise ValueError("Choose a backup destination outside the database, checkpoint, and workspace paths")
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="aura-local-backup-", dir=destination.parent) as temp_name:
        staging = Path(temp_name)
        database_snapshot = staging / DATABASE_FILE
        checkpoint_snapshot = staging / CHECKPOINT_DIRECTORY / CHECKPOINT_FILE
        _snapshot_sqlite(database_path, database_snapshot)
        _snapshot_sqlite(checkpoint_path, checkpoint_snapshot)
        workspace_snapshot = staging / WORKSPACE_FILE
        _archive_workspace(workspace_path, workspace_snapshot)
        payloads = [database_snapshot, checkpoint_snapshot, workspace_snapshot]
        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stores": {
                "database": "SQLite online-backup snapshot",
                "checkpointer": "SQLite online-backup snapshot",
                "workspace": "Workspace files; local API confirmed stopped during capture",
            },
            "files": {
                str(path.relative_to(staging)).replace(os.sep, "/"): _sha256(path)
                for path in payloads
            },
        }
        manifest_path = staging / MANIFEST_FILE
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        archive_path = staging / "backup.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(manifest_path, arcname=MANIFEST_FILE)
            for path in payloads:
                archive.add(path, arcname=str(path.relative_to(staging)).replace(os.sep, "/"))
        destination_created = False
        try:
            with destination.open("xb") as output, archive_path.open("rb") as source:
                destination_created = True
                os.chmod(destination, 0o600)
                shutil.copyfileobj(source, output)
            verify_backup(destination)
        except BaseException:
            if destination_created:
                destination.unlink(missing_ok=True)
            raise
    return destination


def _sqlite_is_healthy(path: Path) -> None:
    database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        result = database.execute("PRAGMA integrity_check").fetchone()
    finally:
        database.close()
    if result != ("ok",):
        raise ValueError(f"SQLite integrity check failed for {path.name}")


def _replace_workspace(root: Path, staged: Path, restore_id: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".aura-restore-{restore_id}-stage"
    previous = root / f".aura-restore-{restore_id}-previous"
    shutil.copytree(staged, stage)
    previous.mkdir()
    moved_old: list[str] = []
    moved_new: list[str] = []
    try:
        for path in list(root.iterdir()):
            if path not in (stage, previous):
                path.rename(previous / path.name)
                moved_old.append(path.name)
        for path in list(stage.iterdir()):
            path.rename(root / path.name)
            moved_new.append(path.name)
    except BaseException:
        for name in reversed(moved_new):
            (root / name).rename(stage / name)
        for name in reversed(moved_old):
            (previous / name).rename(root / name)
        shutil.rmtree(previous)
        shutil.rmtree(stage)
        raise
    shutil.rmtree(previous, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)


def restore_backup(
    archive_path: Path,
    *,
    replace_current_data: bool = False,
    api_stopped: bool = False,
) -> None:
    if not replace_current_data:
        raise ValueError("Restoring replaces current SQLite data and workspace files; pass --replace-current-data to continue")
    if not api_stopped:
        raise ValueError("Stop the local AURA API first, then pass --api-stopped to confirm its stores are idle")
    archive_path = archive_path.expanduser().resolve()
    manifest = verify_backup(archive_path)
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("Unsupported local AURA backup format")
    database_path, checkpoint_path, workspace_path = _configured_paths()
    restore_id = uuid.uuid4().hex

    with tempfile.TemporaryDirectory(prefix="aura-local-restore-") as temp_name:
        staging = Path(temp_name)
        database_snapshot = staging / DATABASE_FILE
        checkpoint_snapshot = staging / CHECKPOINT_DIRECTORY / CHECKPOINT_FILE
        with tarfile.open(archive_path, "r:gz") as archive:
            for name, target in (
                (DATABASE_FILE, database_snapshot),
                (f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_FILE}", checkpoint_snapshot),
            ):
                source = archive.extractfile(name)
                if source is None:
                    raise ValueError(f"Local backup payload cannot be read: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        workspace_snapshot = staging / WORKSPACE_FILE
        with tarfile.open(archive_path, "r:gz") as archive:
            source = archive.extractfile(WORKSPACE_FILE)
            if source is None:
                raise ValueError("Local workspace snapshot cannot be read")
            with source, workspace_snapshot.open("xb") as output:
                shutil.copyfileobj(source, output)
        _sqlite_is_healthy(database_snapshot)
        _sqlite_is_healthy(checkpoint_snapshot)
        restored_workspace = staging / "workspace"
        extract_workspace_archive(workspace_snapshot, restored_workspace)

        targets = ((database_snapshot, database_path), (checkpoint_snapshot, checkpoint_path))
        replacements: list[tuple[Path, Path]] = []
        try:
            for snapshot, target in targets:
                target.parent.mkdir(parents=True, exist_ok=True)
                staged_target = target.with_name(f".{target.name}.{restore_id}.staged")
                shutil.copy2(snapshot, staged_target)
                previous_target = target.with_name(f".{target.name}.{restore_id}.previous")
                if target.exists():
                    target.rename(previous_target)
                try:
                    staged_target.rename(target)
                except BaseException:
                    if previous_target.exists():
                        previous_target.rename(target)
                    raise
                replacements.append((target, previous_target))
                for suffix in ("-wal", "-shm", "-journal"):
                    sidecar = Path(f"{target}{suffix}")
                    if sidecar.exists():
                        previous_sidecar = Path(f"{previous_target}{suffix}")
                        sidecar.rename(previous_sidecar)
                        replacements.append((sidecar, previous_sidecar))
            _replace_workspace(workspace_path, restored_workspace, restore_id)
        except BaseException:
            for current, previous in reversed(replacements):
                if current.exists():
                    current.unlink()
                if previous.exists():
                    previous.rename(current)
            raise
        for _, previous in replacements:
            try:
                previous.unlink(missing_ok=True)
            except OSError:
                # The restored stores are already committed; retain a recovery
                # copy instead of reporting a false restore failure.
                continue


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up or restore local AURA SQLite stores and workspace files.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--verify", type=Path, metavar="ARCHIVE", help="Verify a local backup without extracting it")
    actions.add_argument("--restore", type=Path, metavar="ARCHIVE", help="Restore all stores from a local backup")
    parser.add_argument("destination", nargs="?", type=Path, help="New backup archive path; existing files are never overwritten")
    parser.add_argument("--api-stopped", action="store_true", help="Confirm the local API is stopped and SQLite stores are idle")
    parser.add_argument("--replace-current-data", action="store_true", help="Confirm current SQLite and workspace data may be replaced")
    args = parser.parse_args()
    try:
        if args.verify:
            manifest = verify_backup(args.verify.expanduser().resolve())
            print(f"VERIFIED local AURA backup from {manifest.get('created_at', 'unknown')}: {args.verify}")
        elif args.restore:
            restore_backup(args.restore, replace_current_data=args.replace_current_data, api_stopped=args.api_stopped)
            print(f"Local AURA backup restored: {args.restore}")
        elif args.destination:
            result = create_backup(args.destination, api_stopped=args.api_stopped)
            print(f"Local AURA backup created: {result} ({result.stat().st_size} bytes)")
        else:
            parser.error("provide a backup destination, --verify ARCHIVE, or --restore ARCHIVE")
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError, sqlite3.Error) as exc:
        print(f"Local AURA backup operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
