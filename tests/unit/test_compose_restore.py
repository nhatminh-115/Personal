"""The Compose restore validates data before replacing either durable store."""

import hashlib
import io
import json
import subprocess
import tarfile

import pytest

from scripts import restore_compose


def _make_backup(path, *, valid=True, include_wal=True, include_workspace=True):
    workspace = io.BytesIO()
    with tarfile.open(fileobj=workspace, mode="w:gz") as workspace_tar:
        info = tarfile.TarInfo("restored.txt")
        info.size = len(b"restored workspace")
        workspace_tar.addfile(info, io.BytesIO(b"restored workspace"))
    files = {
        "postgres.dump": b"postgres-dump",
        "checkpoint/aura_checkpoints.db": b"sqlite-checkpoint",
    }
    if include_workspace:
        files["workspace.tar.gz"] = workspace.getvalue()
    if include_wal:
        files["checkpoint/aura_checkpoints.db-wal"] = b"sqlite-wal"
    manifest = {
        "format_version": 2 if include_workspace else 1,
        "created_at": "2026-10-03T00:00:00+00:00",
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
    }
    if not valid:
        manifest["files"]["postgres.dump"] = hashlib.sha256(b"wrong dump").hexdigest()
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [("manifest.json", json.dumps(manifest).encode()), *files.items()]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def test_restore_requires_explicit_confirmation_before_compose_calls(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(restore_compose, "_compose", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError, match="--replace-current-data"):
        restore_compose.restore_backup(tmp_path / "does-not-exist.tar.gz")

    assert calls == []


def test_restore_rejects_corrupt_backup_before_stopping_services(tmp_path, monkeypatch):
    archive = _make_backup(tmp_path / "corrupt.tar.gz", valid=False)
    calls = []
    monkeypatch.setattr(restore_compose, "_compose", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(ValueError, match="checksum failed for postgres.dump"):
        restore_compose.restore_backup(archive, replace_current_data=True)

    assert calls == []


def test_restore_replaces_both_stores_and_restores_running_service_state(tmp_path, monkeypatch):
    archive = _make_backup(tmp_path / "valid.tar.gz")
    calls = []

    def fake_compose(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("ps", "--status", "running"):
            return subprocess.CompletedProcess(args, 0, stdout="aura-app\npostgres\n")
        return subprocess.CompletedProcess(args, 0, stdout="" if kwargs.get("text") else b"")

    monkeypatch.setattr(restore_compose, "_compose", fake_compose)
    restore_compose.restore_backup(archive, replace_current_data=True)

    assert calls[1] == ("stop", "--timeout", "30", "aura-app")
    assert any(call[:3] == ("exec", "-T", "--user") and "chmod" in call for call in calls)
    assert any(call[:4] == ("exec", "-T", "postgres", "pg_restore") for call in calls)
    assert any(call[0] == "cp" and call[-1] == "aura-app:/app/checkpoints/aura_checkpoints.db" for call in calls)
    assert any(call[0] == "cp" and call[-1] == "aura-app:/app/checkpoints/aura_checkpoints.db-wal" for call in calls)
    assert any(call[0] == "cp" and "/app/workspace/.aura-restore-" in call[-1] for call in calls)
    swap_code = next(call[-1] for call in calls if call[0] == "run" and "previous=root/" in call[-1])
    compile(swap_code, "workspace restore command", "exec")
    assert calls[-1] == ("start", "aura-app")


def test_restore_failure_keeps_api_stopped(tmp_path, monkeypatch):
    archive = _make_backup(tmp_path / "valid.tar.gz")
    calls = []

    def fake_compose(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("ps", "--status", "running"):
            return subprocess.CompletedProcess(args, 0, stdout="aura-app\npostgres\n")
        if args[:4] == ("exec", "-T", "postgres", "pg_restore"):
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout="" if kwargs.get("text") else b"")

    monkeypatch.setattr(restore_compose, "_compose", fake_compose)

    with pytest.raises(subprocess.CalledProcessError):
        restore_compose.restore_backup(archive, replace_current_data=True)

    assert calls[1] == ("stop", "--timeout", "30", "aura-app")
    assert ("start", "aura-app") not in calls


def test_restore_preserves_stopped_service_state_and_optional_wal(tmp_path, monkeypatch):
    archive = _make_backup(tmp_path / "without-wal.tar.gz", include_wal=False)
    calls = []

    def fake_compose(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("ps", "--status", "running"):
            return subprocess.CompletedProcess(args, 0, stdout="")
        return subprocess.CompletedProcess(args, 0, stdout="" if kwargs.get("text") else b"")

    monkeypatch.setattr(restore_compose, "_compose", fake_compose)
    restore_compose.restore_backup(archive, replace_current_data=True)

    assert ("start", "postgres") in calls
    assert ("stop", "postgres") in calls
    assert not any(call[-1:] == ("aura-app",) and call[0] in {"start", "stop"} for call in calls)
    assert not any(call[0] == "cp" and call[-1] == "aura-app:/app/checkpoints/aura_checkpoints.db-wal" for call in calls)


def test_legacy_backup_restores_database_and_checkpoint_without_replacing_workspace(tmp_path, monkeypatch):
    archive = _make_backup(tmp_path / "legacy-v1.tar.gz", include_workspace=False)
    calls = []

    def fake_compose(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("ps", "--status", "running"):
            return subprocess.CompletedProcess(args, 0, stdout="")
        return subprocess.CompletedProcess(args, 0, stdout="" if kwargs.get("text") else b"")

    monkeypatch.setattr(restore_compose, "_compose", fake_compose)
    restore_compose.restore_backup(archive, replace_current_data=True)

    assert any(call[0] == "exec" and "pg_restore" in call for call in calls)
    assert not any(call[0] == "cp" and "/app/workspace/" in call[-1] for call in calls)
