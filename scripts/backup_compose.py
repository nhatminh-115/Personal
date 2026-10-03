"""Create a consistent backup of the Docker Compose PostgreSQL and checkpoint stores."""

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
from typing import BinaryIO


CHECKPOINT_DIRECTORY = "checkpoint"
CHECKPOINT_DATABASE = "aura_checkpoints.db"


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


def verify_backup(archive_path: Path) -> dict:
    """Validate archive structure and every payload checksum without extracting files."""
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        allowed = {
            "manifest.json",
            "postgres.dump",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}-wal",
        }
        by_name = {member.name: member for member in members}
        if len(by_name) != len(members) or set(by_name) - allowed:
            raise ValueError("Backup contains duplicate or unexpected archive paths")
        if any(not member.isfile() for member in members):
            raise ValueError("Backup entries must be regular files")
        required = {
            "manifest.json",
            "postgres.dump",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
        }
        if not required <= set(by_name):
            raise ValueError("Backup is missing a required data store")

        manifest_stream = archive.extractfile(by_name["manifest.json"])
        if manifest_stream is None:
            raise ValueError("Backup manifest cannot be read")
        manifest = json.load(manifest_stream)
        if not isinstance(manifest, dict):
            raise ValueError("Backup manifest must be a JSON object")
        if manifest.get("format_version") != 1:
            raise ValueError("Unsupported AURA backup format")
        files = manifest.get("files")
        payload_names = set(by_name) - {"manifest.json"}
        if not isinstance(files, dict) or set(files) != payload_names:
            raise ValueError("Backup manifest does not match its data files")
        for name in sorted(payload_names):
            stream = archive.extractfile(by_name[name])
            if stream is None or _sha256_stream(stream) != files[name]:
                raise ValueError(f"Backup checksum failed for {name}")
        return manifest


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

            # SQLite WAL mode keeps committed updates in a sidecar until checkpointed.
            wal = checkpoint_dir / f"{CHECKPOINT_DATABASE}-wal"
            payloads = [database_dump, checkpoint_db, *([wal] if wal.exists() else [])]
            manifest = {
                "format_version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "stores": {
                    "database": "PostgreSQL custom-format dump",
                    "checkpointer": "SQLite database and optional WAL; API stopped during capture",
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
        description="Back up both durable AURA Compose stores into one checksummed archive."
    )
    parser.add_argument(
        "destination",
        nargs="?",
        type=Path,
        help="New .tar.gz path; existing files are never overwritten",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        metavar="ARCHIVE",
        help="Validate a backup without extracting it",
    )
    args = parser.parse_args()
    try:
        if args.verify:
            manifest = verify_backup(args.verify)
            print(f"Backup verified: {args.verify} (created {manifest['created_at']})")
            return 0
        if args.destination is None:
            parser.error("destination is required unless --verify is used")
        result = create_backup(args.destination)
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"AURA Compose backup operation failed: {exc}", file=sys.stderr)
        return 1
    print(f"AURA Compose backup created: {result} ({result.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
