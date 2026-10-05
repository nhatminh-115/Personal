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


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _validate_workspace_archive(archive_path: Path) -> None:
    """Reject unsafe or unsupported entries before a workspace archive can be restored."""
    with tarfile.open(archive_path, "r:gz") as archive:
        seen: dict[str, bool] = {}
        for member in archive.getmembers():
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
            if not (member.isfile() or member.isdir()):
                raise ValueError("Workspace backup entries must be regular files or directories")
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
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod((member.mode & 0o777) | 0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Workspace backup file cannot be read: {member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod((member.mode & 0o777) | 0o600)


def verify_backup(archive_path: Path) -> dict:
    """Validate archive structure and every payload checksum without extracting files."""
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        allowed = {
            "manifest.json",
            "postgres.dump",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}-wal",
            WORKSPACE_ARCHIVE,
        }
        by_name = {member.name: member for member in members}
        if len(by_name) != len(members) or set(by_name) - allowed:
            raise ValueError("Backup contains duplicate or unexpected archive paths")
        if "manifest.json" not in by_name:
            raise ValueError("Backup is missing a manifest")
        if any(not member.isfile() for member in members):
            raise ValueError("Backup entries must be regular files")
        required = {
            "manifest.json",
            "postgres.dump",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
        }
        manifest_stream = archive.extractfile(by_name["manifest.json"])
        if manifest_stream is None:
            raise ValueError("Backup manifest cannot be read")
        manifest = json.load(manifest_stream)
        if not isinstance(manifest, dict):
            raise ValueError("Backup manifest must be a JSON object")
        format_version = manifest.get("format_version")
        if format_version not in {1, 2}:
            raise ValueError("Unsupported AURA backup format")
        if format_version == 2:
            required.add(WORKSPACE_ARCHIVE)
        elif WORKSPACE_ARCHIVE in by_name:
            raise ValueError("Workspace backup requires format version 2")
        if not required <= set(by_name):
            raise ValueError("Backup is missing a required data store")
        files = manifest.get("files")
        payload_names = set(by_name) - {"manifest.json"}
        if not isinstance(files, dict) or set(files) != payload_names:
            raise ValueError("Backup manifest does not match its data files")
        for name in sorted(payload_names):
            stream = archive.extractfile(by_name[name])
            if stream is None or _sha256_stream(stream) != files[name]:
                raise ValueError(f"Backup checksum failed for {name}")
        if WORKSPACE_ARCHIVE in by_name:
            workspace_stream = archive.extractfile(by_name[WORKSPACE_ARCHIVE])
            if workspace_stream is None:
                raise ValueError("Workspace backup cannot be read")
            with tempfile.TemporaryDirectory(prefix="aura-workspace-verify-") as temp_name:
                workspace_path = Path(temp_name) / WORKSPACE_ARCHIVE
                with workspace_path.open("xb") as workspace_file:
                    shutil.copyfileobj(workspace_stream, workspace_file)
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
        description="Back up AURA Compose database, checkpoints, and workspace into one checksummed archive."
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
                print(f"No AURA Compose backups found in {args.list.expanduser().resolve()}")
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
        print(f"AURA Compose backup operation failed: {exc}", file=sys.stderr)
        return 1
    print(f"AURA Compose backup created: {result} ({result.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
