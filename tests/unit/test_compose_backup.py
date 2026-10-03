"""The Compose backup preserves both stores and restores service state."""

import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import backup_compose


def _fake_compose(monkeypatch, *, api_running=True, fail_checkpoint=False):
    calls: list[list[str]] = []
    checkpoint = b"sqlite-checkpoint"
    wal = b"sqlite-wal"

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[2:5] == ["ps", "--status", "running"]:
            return subprocess.CompletedProcess(command, 0, stdout="aura-app\n" if api_running else "")
        if fail_checkpoint and command[2:4] == ["cp", "aura-app:/app/checkpoints/."]:
            raise subprocess.CalledProcessError(1, command)
        if command[2:4] == ["cp", "aura-app:/app/checkpoints/."]:
            Path(command[-1], "aura_checkpoints.db").write_bytes(checkpoint)
            Path(command[-1], "aura_checkpoints.db-wal").write_bytes(wal)
        elif "pg_dump" in command:
            kwargs["stdout"].write(b"postgres-dump")
        return subprocess.CompletedProcess(command, 0, stdout="" if kwargs.get("text") else b"")

    monkeypatch.setattr(backup_compose, "_run_command", fake_run)
    return calls, checkpoint, wal


def test_backup_contains_both_stores_and_checksums(tmp_path, monkeypatch):
    calls, checkpoint, wal = _fake_compose(monkeypatch)
    destination = backup_compose.create_backup(tmp_path / "aura.tar.gz")

    assert ["docker", "compose", "stop", "--timeout", "30", "aura-app"] in calls
    assert calls[-1] == ["docker", "compose", "start", "aura-app"]
    with tarfile.open(destination, "r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert archive.extractfile("postgres.dump").read() == b"postgres-dump"
        assert archive.extractfile("checkpoint/aura_checkpoints.db").read() == checkpoint
        assert archive.extractfile("checkpoint/aura_checkpoints.db-wal").read() == wal
    assert manifest["format_version"] == 1
    assert manifest["files"] == {
        "postgres.dump": hashlib.sha256(b"postgres-dump").hexdigest(),
        "checkpoint/aura_checkpoints.db": hashlib.sha256(checkpoint).hexdigest(),
        "checkpoint/aura_checkpoints.db-wal": hashlib.sha256(wal).hexdigest(),
    }
    assert backup_compose.verify_backup(destination) == manifest


def test_backup_verification_rejects_payload_tampering(tmp_path):
    manifest = {
        "format_version": 1,
        "created_at": "2026-10-03T00:00:00+00:00",
        "files": {
            "postgres.dump": hashlib.sha256(b"expected dump").hexdigest(),
            "checkpoint/aura_checkpoints.db": hashlib.sha256(b"checkpoint").hexdigest(),
        },
    }
    archive_path = tmp_path / "tampered.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, content in (
            ("manifest.json", json.dumps(manifest).encode()),
            ("postgres.dump", b"modified dump"),
            ("checkpoint/aura_checkpoints.db", b"checkpoint"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    with pytest.raises(ValueError, match="checksum failed for postgres.dump"):
        backup_compose.verify_backup(archive_path)


def test_list_backups_reports_verified_and_invalid_archives_without_changing_them(tmp_path, monkeypatch):
    _fake_compose(monkeypatch, api_running=False)
    verified_path = backup_compose.create_backup(tmp_path / "aura-2026-10-03.tar.gz")
    invalid_path = tmp_path / "aura-broken.tar.gz"
    invalid_path.write_bytes(b"not a backup")
    original_bytes = invalid_path.read_bytes()

    backups = backup_compose.list_backups(tmp_path)

    assert [backup["path"] for backup in backups] == [str(verified_path.resolve()), str(invalid_path.resolve())]
    assert [backup["status"] for backup in backups] == ["verified", "invalid"]
    assert backups[0]["created_at"]
    assert invalid_path.read_bytes() == original_bytes
    assert verified_path.is_file()


def test_list_backups_requires_an_existing_directory(tmp_path):
    with pytest.raises(NotADirectoryError, match="Backup directory does not exist"):
        backup_compose.list_backups(tmp_path / "missing")


def test_list_command_returns_nonzero_when_an_archive_is_invalid(tmp_path, monkeypatch, capsys):
    (tmp_path / "broken.tar.gz").write_bytes(b"not a backup")
    monkeypatch.setattr("sys.argv", ["backup_compose.py", "--list", str(tmp_path)])

    assert backup_compose.main() == 1
    output = capsys.readouterr().out
    assert "INVALID" in output
    assert "0 verified; 1 invalid" in output


def test_backup_does_not_change_stopped_api_state(tmp_path, monkeypatch):
    calls, _, _ = _fake_compose(monkeypatch, api_running=False)
    backup_compose.create_backup(tmp_path / "aura.tar.gz")

    assert not any(command[2] in {"stop", "start"} for command in calls if len(command) > 2)


def test_backup_restarts_api_if_checkpoint_capture_fails(tmp_path, monkeypatch):
    calls, _, _ = _fake_compose(monkeypatch, fail_checkpoint=True)

    with pytest.raises(subprocess.CalledProcessError):
        backup_compose.create_backup(tmp_path / "aura.tar.gz")

    assert calls[-1] == ["docker", "compose", "start", "aura-app"]
    assert not (tmp_path / "aura.tar.gz").exists()


def test_backup_restarts_api_if_stop_fails_mid_transition(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[2:5] == ["ps", "--status", "running"]:
            return subprocess.CompletedProcess(command, 0, stdout="aura-app\n")
        if command[2:3] == ["stop"]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, stdout="" if kwargs.get("text") else b"")

    monkeypatch.setattr(backup_compose, "_run_command", fake_run)

    with pytest.raises(subprocess.CalledProcessError):
        backup_compose.create_backup(tmp_path / "aura.tar.gz")

    assert calls[-1] == ["docker", "compose", "start", "aura-app"]
    assert not (tmp_path / "aura.tar.gz").exists()


def test_backup_rejects_and_removes_archive_that_fails_post_write_verification(tmp_path, monkeypatch):
    calls, _, _ = _fake_compose(monkeypatch)
    destination = tmp_path / "aura.tar.gz"
    real_verify = backup_compose.verify_backup
    verification_targets = []

    def fail_written_archive(path):
        verification_targets.append(path)
        if path == destination.resolve():
            raise ValueError("post-write verification failed")
        return real_verify(path)

    monkeypatch.setattr(backup_compose, "verify_backup", fail_written_archive)

    with pytest.raises(ValueError, match="post-write verification"):
        backup_compose.create_backup(destination)

    assert verification_targets == [destination.resolve()]
    assert calls[-1] == ["docker", "compose", "start", "aura-app"]
    assert not destination.exists()


def test_backup_never_overwrites_an_existing_archive(tmp_path, monkeypatch):
    calls, _, _ = _fake_compose(monkeypatch)
    destination = tmp_path / "aura.tar.gz"
    destination.write_bytes(b"keep me")

    with pytest.raises(FileExistsError):
        backup_compose.create_backup(destination)

    assert destination.read_bytes() == b"keep me"
    assert not calls
