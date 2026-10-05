"""Local SQLite backups preserve all AURA stores and restore only when explicitly confirmed."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy.engine import URL

from scripts import backup_local


def _configure_local_stores(monkeypatch, root: Path) -> tuple[Path, Path, Path]:
    database = root / "aura.db"
    checkpoint = root / "aura_checkpoints.db"
    workspace = root / "workspace"
    for path, table, value in (
        (database, "app_data", "before"),
        (checkpoint, "checkpoint_data", "checkpoint-before"),
    ):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(f"CREATE TABLE {table} (value TEXT)")
            connection.execute(f"INSERT INTO {table} VALUES (?)", (value,))
            connection.commit()
    (workspace / "notes").mkdir(parents=True)
    (workspace / "notes" / "saved.txt").write_text("before workspace", encoding="utf-8")
    monkeypatch.setattr(backup_local.settings, "DATABASE_URL", URL.create("sqlite+aiosqlite", database=str(database)).render_as_string())
    monkeypatch.setattr(backup_local.settings, "CHECKPOINT_DB_PATH", checkpoint)
    monkeypatch.setattr(backup_local.settings, "AURA_WORKSPACE_ROOT", workspace)
    return database, checkpoint, workspace


def test_local_backup_snapshots_sqlite_and_workspace_and_restores_them(tmp_path, monkeypatch):
    database, checkpoint, workspace = _configure_local_stores(monkeypatch, tmp_path)
    archive = backup_local.create_backup(tmp_path / "backups" / "aura-local.tar.gz", api_stopped=True)

    assert backup_local.verify_backup(archive)["format_version"] == 1
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("UPDATE app_data SET value='after'")
        connection.commit()
    with closing(sqlite3.connect(checkpoint)) as connection:
        connection.execute("UPDATE checkpoint_data SET value='checkpoint-after'")
        connection.commit()
    (workspace / "notes" / "saved.txt").write_text("after workspace", encoding="utf-8")
    (workspace / "new.txt").write_text("remove on restore", encoding="utf-8")

    backup_local.restore_backup(archive, replace_current_data=True, api_stopped=True)

    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT value FROM app_data").fetchone() == ("before",)
    with closing(sqlite3.connect(checkpoint)) as connection:
        assert connection.execute("SELECT value FROM checkpoint_data").fetchone() == ("checkpoint-before",)
    assert (workspace / "notes" / "saved.txt").read_text(encoding="utf-8") == "before workspace"
    assert not (workspace / "new.txt").exists()


def test_local_backup_requires_offline_confirmation_and_never_overwrites(tmp_path, monkeypatch):
    _configure_local_stores(monkeypatch, tmp_path)
    destination = tmp_path / "backup.tar.gz"
    with pytest.raises(ValueError, match="--api-stopped"):
        backup_local.create_backup(destination)
    assert not destination.exists()

    backup_local.create_backup(destination, api_stopped=True)
    original = destination.read_bytes()
    with pytest.raises(FileExistsError):
        backup_local.create_backup(destination, api_stopped=True)
    assert destination.read_bytes() == original


def test_local_restore_requires_both_confirmation_flags_before_writing(tmp_path, monkeypatch):
    database, _, _ = _configure_local_stores(monkeypatch, tmp_path)
    archive = backup_local.create_backup(tmp_path / "backup.tar.gz", api_stopped=True)
    before = database.read_bytes()

    with pytest.raises(ValueError, match="--replace-current-data"):
        backup_local.restore_backup(archive, api_stopped=True)
    with pytest.raises(ValueError, match="--api-stopped"):
        backup_local.restore_backup(archive, replace_current_data=True)
    assert database.read_bytes() == before
