"""Restore AURA Docker Compose data, checkpoints, and workspace from an archive."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup_compose import (
    CHECKPOINT_DATABASE,
    CHECKPOINT_DIRECTORY,
    WORKSPACE_ARCHIVE,
    _compose,
    extract_workspace_archive,
    verify_backup,
)


def _extract_verified_backup(archive_path: Path, destination: Path) -> None:
    """Copy only the allowlisted, checksum-verified payload files to a fresh directory."""
    verify_backup(archive_path)
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        for name in (
            "postgres.dump",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}",
            f"{CHECKPOINT_DIRECTORY}/{CHECKPOINT_DATABASE}-wal",
            WORKSPACE_ARCHIVE,
        ):
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
        raise ValueError("Restoring replaces current database, checkpoint, and workspace data; pass --replace-current-data to continue")

    archive_path = archive_path.expanduser().resolve()
    manifest = verify_backup(archive_path)
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
        workspace_archive = staging / WORKSPACE_ARCHIVE
        workspace_restore = staging / "workspace"
        if workspace_archive.is_file():
            extract_workspace_archive(workspace_archive, workspace_restore)
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
            if manifest.get("format_version") == 2:
                restore_id = uuid.uuid4().hex
                stage_name = f".aura-restore-{restore_id}-stage"
                previous_name = f".aura-restore-{restore_id}-previous"
                create_stage = (
                    "from pathlib import Path; "
                    f"Path('/app/workspace/{stage_name}').mkdir()"
                )
                _compose("run", "--rm", "--no-deps", "--user", "0", "--entrypoint", "python", "aura-app", "-c", create_stage)
                _compose("cp", f"{workspace_restore}{os.sep}.", f"aura-app:/app/workspace/{stage_name}")
                workspace_swap = (
                    "import os, pwd, shutil\n"
                    "from pathlib import Path\n"
                    "root=Path('/app/workspace')\n"
                    f"stage=root/{stage_name!r}\n"
                    f"previous=root/{previous_name!r}\n"
                    "if previous.exists(): raise RuntimeError('A workspace recovery directory already exists')\n"
                    "if not stage.is_dir(): raise RuntimeError('Workspace restore staging directory is missing')\n"
                    "account=pwd.getpwnam('aurauser')\n"
                    "for path in [stage, *stage.rglob('*')]: os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)\n"
                    "previous.mkdir()\n"
                    "moved_old=[]\n"
                    "moved_new=[]\n"
                    "try:\n"
                    " for path in list(root.iterdir()):\n"
                    "  if path not in (stage, previous):\n"
                    "   path.rename(previous/path.name)\n"
                    "   moved_old.append(path.name)\n"
                    " for path in list(stage.iterdir()):\n"
                    "  path.rename(root/path.name)\n"
                    "  moved_new.append(path.name)\n"
                    "except BaseException:\n"
                    " for name in reversed(moved_new): (root/name).rename(stage/name)\n"
                    " for name in reversed(moved_old): (previous/name).rename(root/name)\n"
                    " shutil.rmtree(previous)\n"
                    " raise\n"
                    "shutil.rmtree(previous)\n"
                    "shutil.rmtree(stage)"
                )
                _compose("run", "--rm", "--no-deps", "--user", "0", "--entrypoint", "python", "aura-app", "-c", workspace_swap)
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
    parser = argparse.ArgumentParser(description="Restore AURA Compose database, checkpoints, and workspace files from a verified archive.")
    parser.add_argument("archive", type=Path, help="Verified AURA .tar.gz backup")
    parser.add_argument(
        "--replace-current-data",
        action="store_true",
        help="Confirm that the existing PostgreSQL database, checkpoint, and workspace files will be replaced",
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
