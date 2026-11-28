"""Create a consistent backup of the Docker Compose database, checkpoints, and workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import BinaryIO


CHECKPOINT_DIRECTORY = "checkpoint"
CHECKPOINT_DATABASE = "aura_checkpoints.db"
WORKSPACE_ARCHIVE = "workspace.tar.gz"

MAX_WORKSPACE_ARCHIVE_ENTRIES = 100_000
MAX_WORKSPACE_MEMBER_BYTES = 2 * 1024**3
MAX_WORKSPACE_TOTAL_BYTES = 8 * 1024**3
MAX_BACKUP_ARCHIVE_ENTRIES = 5
MAX_BACKUP_MEMBER_BYTES = 10 * 1024**3
MAX_BACKUP_TOTAL_BYTES = 20 * 1024**3
MAX_BACKUP_MANIFEST_BYTES = 1024 * 1024


def _run_command(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, **kwargs)


def _compose(
    *arguments: str,
    stdout: BinaryIO | None = None,
    text: bool = False,
) -> subprocess.CompletedProcess:
    return _run_command(
        ["docker", "compose", *arguments],
        check=True,
        stdout=stdout,
        text=text,
        capture_output=stdout is None,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _consume_archive_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    *,
    output: BinaryIO | None = None,
    capture: bool = False,
) -> tuple[str, bytes | None]:
    """Read one declared tar member in bounded chunks while optionally hashing/copying it."""
    source = archive.extractfile(member)
    if source is None:
        raise ValueError(f"Backup archive entry cannot be read: {member.name}")
    digest = hashlib.sha256()
    captured = bytearray() if capture else None
    remaining = member.size
    with source:
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError(f"Backup archive entry is truncated: {member.name}")
            remaining -= len(chunk)
            digest.update(chunk)
            if output is not None:
                output.write(chunk)
            if captured is not None:
                captured.extend(chunk)
    return digest.hexdigest(), bytes(captured) if captured is not None else None

def _validate_workspace_archive(archive_path: Path) -> None:
    """Reject unsafe, oversized, or unsupported entries before workspace restore."""
    seen: dict[str, bool] = {}
    total_bytes = 0
    with tarfile.open(archive_path, "r|gz") as archive:
        while True:
            member = archive.next()
            if member is None:
                break
            if len(seen) >= MAX_WORKSPACE_ARCHIVE_ENTRIES:
                raise ValueError("Workspace backup contains too many entries")
            name = member.name
            path = PurePosixPath(name)
            if (
                not name
                or path.is_absolute()
                or path.as_posix() != name
                or ":" in name
                or any(part in {"", ".", ".."} for part in path.parts)
                or "\\" in name
                or name in seen
            ):
                raise ValueError("Workspace backup contains an unsafe or duplicate path")
            if not (member.isfile() or member.isdir()) or member.issparse():
                raise ValueError("Workspace backup entries must be regular files or directories")
            if member.size < 0 or member.size > MAX_WORKSPACE_MEMBER_BYTES:
                raise ValueError("Workspace backup file exceeds the size limit")
            if member.isdir() and member.size != 0:
                raise ValueError("Workspace backup directories cannot contain payload data")
            if member.isfile():
                total_bytes += member.size
                if total_bytes > MAX_WORKSPACE_TOTAL_BYTES:
                    raise ValueError("Workspace backup exceeds the expanded size limit")
            seen[name] = member.isdir()

    for name in seen:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            parent_name = parent.as_posix()
            if parent_name in seen and not seen[parent_name]:
                raise ValueError("Workspace backup path is nested beneath a regular file")
            parent = parent.parent


def extract_workspace_archive(archive_path: Path, destination: Path) -> None:
    """Extract a validated workspace archive without tarfile's path-based extraction."""
    _validate_workspace_archive(archive_path)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r|gz") as archive:
        while True:
            member = archive.next()
            if member is None:
                break
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod((member.mode & 0o777) | 0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Workspace backup file cannot be read: {member.name}")
            remaining = member.size
            with source, target.open("xb") as output:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError(f"Workspace backup file is truncated: {member.name}")
                    output.write(chunk)
                    remaining -= len(chunk)
            target.chmod((member.mode & 0o777) | 0o600)


def verify_backup(archive_path: Path) -> dict:
    """Validate a bounded backup stream and every payload checksum without extracting files."""
    allowed = {
        "manifest.json",
        "postgres.dump",
        f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
        f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}-wal",
        WORKSPACE_ARCHIVE,
    }
    names: set[str] = set()
    payload_hashes: dict[str, str] = {}
    total_bytes = 0
    manifest_bytes: bytes | None = None

    with tempfile.TemporaryDirectory(prefix="aura-workspace-verify-") as temp_name:
        workspace_path = Path(temp_name) / WORKSPACE_ARCHIVE
        with tarfile.open(archive_path, "r|gz") as archive:
            while True:
                member = archive.next()
                if member is None:
                    break
                if len(names) >= MAX_BACKUP_ARCHIVE_ENTRIES:
                    raise ValueError("Backup contains too many archive entries")
                name = member.name
                if name not in allowed or name in names:
                    raise ValueError("Backup contains duplicate or unexpected archive paths")
                if not member.isfile() or member.issparse():
                    raise ValueError("Backup entries must be regular files")
                if member.size < 0:
                    raise ValueError("Backup archive entry has an invalid size")
                if name != "manifest.json" and member.size > MAX_BACKUP_MEMBER_BYTES:
                    raise ValueError("Backup archive entry exceeds the size limit")
                total_bytes += member.size
                if total_bytes > MAX_BACKUP_TOTAL_BYTES:
                    raise ValueError("Backup archive exceeds the total size limit")
                names.add(name)

                if name == "manifest.json":
                    if member.size > MAX_BACKUP_MANIFEST_BYTES:
                        raise ValueError("Backup manifest exceeds the size limit")
                    _, manifest_bytes = _consume_archive_member(archive, member, capture=True)
                    continue

                output = workspace_path.open("xb") if name == WORKSPACE_ARCHIVE else None
                try:
                    if output is None:
                        digest, _ = _consume_archive_member(archive, member)
                    else:
                        with output:
                            digest, _ = _consume_archive_member(archive, member, output=output)
                finally:
                    if output is not None and not output.closed:
                        output.close()
                payload_hashes[name] = digest

        if manifest_bytes is None:
            raise ValueError("Backup is missing a manifest")
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict):
            raise ValueError("Backup manifest must be a JSON object")
        format_version = manifest.get("format_version")
        if format_version not in {1, 2}:
            raise ValueError("Unsupported Kuractus backup format")
        required = {
            "manifest.json",
            "postgres.dump",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
        }
        if format_version == 2:
            required.add(WORKSPACE_ARCHIVE)
        elif WORKSPACE_ARCHIVE in names:
            raise ValueError("Workspace backup requires format version 2")
        if not required <= names:
            raise ValueError("Backup is missing a required data store")
        payload_names = names - {"manifest.json"}
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != payload_names:
            raise ValueError("Backup manifest does not match its data files")
        for name in sorted(payload_names):
            if payload_hashes.get(name) != files[name]:
                raise ValueError(f"Backup checksum failed for {name}")
        if WORKSPACE_ARCHIVE in names:
            _validate_workspace_archive(workspace_path)
        return manifest

def list_backups(directory: Path) -> list[dict[str, str | int | None]]:
    """Inspect direct .tar.gz children without extracting or modifying archives."""
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise NotADirectoryError(f"Backup directory does not exist: {directory}")

    backups: list[dict[str, str | int | None]] = []
    for archive_path in sorted(directory.glob("*.tar.gz"), key=lambda path: path.name.casefold()):
        if not archive_path.is_file():
            continue
        size_bytes: int | None = None
        try:
            size_bytes = archive_path.stat().st_size
            manifest = verify_backup(archive_path)
        except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
            backups.append({
                "path": str(archive_path),
                "status": "invalid",
                "created_at": None,
                "size_bytes": size_bytes,
                "error": str(exc),
            })
            continue
        backups.append({
            "path": str(archive_path),
            "status": "verified",
            "created_at": str(manifest.get("created_at", "unknown")),
            "size_bytes": size_bytes,
            "error": None,
        })
    return backups


def create_backup(destination: Path) -> Path:
    """Write a non-overwriting archive while the API is stopped between stores."""
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing backup: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    running_services = _compose("ps", "--status", "running", "--services", text=True).stdout.splitlines()
    api_was_running = "aura-app" in running_services

    primary_error: BaseException | None = None
    destination_created = False
    try:
        if api_was_running:
            _compose("stop", "--timeout", "30", "aura-app")

        with tempfile.TemporaryDirectory(prefix="aura-compose-backup-", dir=destination.parent) as temp_name:
            staging = Path(temp_name)
            database_dump = staging / "postgres.dump"
            with database_dump.open("wb") as dump_stream:
                _compose(
                    "exec", "-T", "postgres", "pg_dump", "--format=custom", "--no-owner", "-U", "aura", "-d", "aura",
                    stdout=dump_stream,
                )

            checkpoint_dir = staging / CHECKPOINT_DIRECTORY
            checkpoint_dir.mkdir()
            _compose("cp", "aura-app:/app/checkpoints/.", str(checkpoint_dir))
            checkpoint_db = checkpoint_dir / CHECKPOINT_DATABASE
            if not checkpoint_db.is_file():
                raise RuntimeError(f"Compose did not copy the checkpoint database to {checkpoint_db}")

            workspace_dir = staging / "workspace"
            workspace_dir.mkdir()
            _compose("cp", "aura-app:/app/workspace/.", str(workspace_dir))
            workspace_archive = staging / WORKSPACE_ARCHIVE
            with tarfile.open(workspace_archive, "w:gz") as workspace_tar:
                for path in sorted(workspace_dir.rglob("*"), key=lambda item: item.relative_to(workspace_dir).as_posix()):
                    if path.is_symlink():
                        raise ValueError("Workspace backup does not support symbolic links")
                    if path.is_dir():
                        workspace_tar.add(path, arcname=path.relative_to(workspace_dir).as_posix(), recursive=False)
                    elif path.is_file():
                        workspace_tar.add(path, arcname=path.relative_to(workspace_dir).as_posix(), recursive=False)
                    else:
                        raise ValueError("Workspace backup contains a non-regular filesystem entry")
            _validate_workspace_archive(workspace_archive)

            # SQLite WAL mode keeps committed updates in a sidecar until checkpointed.
            wal = checkpoint_dir / f"{CHECKPOINT_DATABASE}-wal"
            payloads = [database_dump, checkpoint_db, *([wal] if wal.exists() else []), workspace_archive]
            manifest = {
                "format_version": 2,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "stores": {
                    "database": "PostgreSQL custom-format dump",
                    "checkpointer": "SQLite database and optional WAL; API stopped during capture",
                    "workspace": "Workspace volume files; API stopped during capture",
                },
                "files": {
                    str(path.relative_to(staging)).replace(os.sep, "/"): _sha256(path)
                    for path in payloads
                },
            }
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            archive_temp = staging / "backup.tar.gz"
            with tarfile.open(archive_temp, "w:gz") as archive:
                archive.add(manifest_path, arcname="manifest.json")
                for path in payloads:
                    archive.add(path, arcname=str(path.relative_to(staging)).replace(os.sep, "/"))

            # Reserve the final name exclusively so concurrent runs cannot overwrite data.
            with destination.open("xb") as output:
                destination_created = True
                os.chmod(destination, 0o600)
                with archive_temp.open("rb") as source:
                    shutil.copyfileobj(source, output)
            verify_backup(destination)
    except BaseException as exc:
        primary_error = exc
        if destination_created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        if api_was_running:
            try:
                _compose("start", "aura-app")
            except Exception as restart_error:
                if primary_error is None:
                    raise
                primary_error.add_note(f"Also failed to restart aura-app after backup: {restart_error}")

    return destination


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Back up Kuractus Compose database, checkpoints, and workspace into one checksummed archive."
    )
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        help="New .tar.gz path; existing files are never overwritten",
    )
    inspections = parser.add_mutually_exclusive_group()
    inspections.add_argument(
        "--verify",
        type=Path,
        metavar="ARCHIVE",
        help="Validate a backup without extracting it",
    )
    inspections.add_argument(
        "--list",
        type=Path,
        metavar="DIRECTORY",
        help="List direct .tar.gz backups and report checksum verification status",
    )
    args = parser.parse_args()
    try:
        if args.list:
            if args.destination is not None:
                parser.error("destination cannot be combined with --list")
            backups = list_backups(args.list)
            if not backups:
                print(f"No Kuractus Compose backups found in {args.list.expanduser().resolve()}")
                return 0
            for backup in backups:
                size = backup["size_bytes"]
                size_text = f"{size} bytes" if size is not None else "size unavailable"
                if backup["status"] == "verified":
                    print(f"VERIFIED  {backup['created_at']}  {size_text}  {backup['path']}")
                else:
                    print(f"INVALID   {size_text}  {backup['path']} — {backup['error']}")
            invalid_count = sum(backup["status"] == "invalid" for backup in backups)
            print(f"{len(backups) - invalid_count} verified; {invalid_count} invalid")
            return 1 if invalid_count else 0
        if args.verify:
            manifest = verify_backup(args.verify)
            print(f"Backup verified: {args.verify} (created {manifest['created_at']})")
            return 0
        if args.destination is None:
            parser.error("destination is required unless --verify or --list is used")
        result = create_backup(args.destination)
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"Kuractus Compose backup operation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Kuractus Compose backup created: {result} ({result.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
