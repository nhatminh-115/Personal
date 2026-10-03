"""Restore both durable AURA Docker Compose stores from a verified archive."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup_compose import CHECKPOINT_DATABASE, CHECKPOINT_DIRECTORY, _compose, verify_backup


def _extract_verified_backup(archive_path: Path, destination: Path) -> None:
    """Copy only the allowlisted, checksum-verified payload files to a fresh directory."""
    verify_backup(archive_path)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for name in ("postgres.dump", f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}", f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}-wal"):
            try:
                member = archive.getmember(name)
            except KeyError:
                continue
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"Backup payload cannot be read: {name}")
            target = destination.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def restore_backup(archive_path: Path, *, replace_current_data: bool = False) -> None:
    """Restore a verified backup, preserving service state on success and failing closed."""
    if not replace_current_data:
        raise ValueError("Restoring replaces current database and checkpoint data; pass --replace-current-data to continue")

    archive_path = archive_path.expanduser().resolve()
    verify_backup(archive_path)
    running_services = set(_compose("ps", "--status", "running", "--services", text=True).stdout.splitlines())
    api_was_running = "aura-app" in running_services
    postgres_was_running = "postgres" in running_services
    postgres_should_run = postgres_was_running or api_was_running

    with tempfile.TemporaryDirectory(prefix="aura-compose-restore-") as staging_name:
        staging = Path(staging_name)
        _extract_verified_backup(archive_path, staging)
        postgres_dump = staging / "postgres.dump"
        checkpoint_db = staging / CHECKPOINT_DIRECTORY / CHECKPOINT_DATABASE
        checkpoint_wal = staging / CHECKPOINT_DIRECTORY / f"{CHECKPOINT_DATABASE}-wal"
        if api_was_running:
            try:
                _compose("stop", "--timeout", "30", "aura-app")
            except Exception as stop_error:
                try:
                    _compose("start", "aura-app")
                except Exception as restart_error:
                    stop_error.add_note(f"Also failed to restart aura-app after stop failed: {restart_error}")
                raise

        postgres_started_by_us = False
        restore_error: BaseException | None = None
        try:
            if not postgres_was_running:
                postgres_started_by_us = True
                _compose("start", "postgres")
            _compose("cp", str(postgres_dump), "postgres:/tmp/aura-postgres.dump")
            _compose("exec", "-T", "--user", "0", "postgres", "chmod", "644", "/tmp/aura-postgres.dump")
            _compose("exec", "-T", "postgres", "pg_restore", "--clean", "--if-exists", "--no-owner", "-U", "aura", "-d", "aura", "/tmp/aura-postgres.dump")
            _compose(
                "run", "--rm", "--no-deps", "--user", "0", "--entrypoint", "sh", "aura-app", "-c",
                "rm -f /app/checkpoints/aura_checkpoints.db-wal /app/checkpoints/aura_checkpoints.db-shm",
            )
            _compose("cp", str(checkpoint_db), f"aura-app:/app/checkpoints/{CHECKPOINT_DATABASE}")
            if checkpoint_wal.is_file():
                _compose("cp", str(checkpoint_wal), f"aura-app:/app/checkpoints/{CHECKPOINT_DATABASE}-wal")
            _compose(
                "run", "--rm", "--no-deps", "--user", "0", "--entrypoint", "sh", "aura-app", "-c",
                "chown -R aurauser:aurauser /app/checkpoints/aura_checkpoints.db*",
            )
        except BaseException as exc:
            restore_error = exc
            raise
        finally:
            try:
                if postgres_started_by_us and not postgres_should_run:
                    _compose("stop", "postgres")
                if api_was_running and restore_error is None:
                    _compose("start", "aura-app")
            except Exception as cleanup_error:
                if restore_error is None:
                    raise
                restore_error.add_note(f"Also failed to restore Compose service state: {cleanup_error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore both durable AURA Compose stores from a verified backup.")
    parser.add_argument("archive", type=Path, help="Verified AURA .tar.gz backup")
    parser.add_argument(
        "--replace-current-data",
        action="store_true",
        help="Confirm that the existing PostgreSQL database and checkpoint will be replaced",
    )
    args = parser.parse_args()
    try:
        restore_backup(args.archive, replace_current_data=args.replace_current_data)
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f"AURA Compose restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"AURA Compose backup restored: {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
