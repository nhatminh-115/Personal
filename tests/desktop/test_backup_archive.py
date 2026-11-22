import json
import zipfile

import pytest

from desktop.data_backup import _checked_members


def _archive(tmp_path, entries):
    path = tmp_path / "backup.aurabackup"
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return zipfile.ZipFile(path)


def test_backup_archive_accepts_supported_database_and_workspace(tmp_path):
    archive = _archive(tmp_path, [
        ("manifest.json", json.dumps({"format": "aura-desktop-backup", "format_version": 1})),
        ("database/aura.dump", b"pgdump"),
        ("workspace/notes/plan.md", b"local file"),
    ])
    with archive:
        members = _checked_members(archive)
    assert {item.filename for item in members} >= {"manifest.json", "database/aura.dump", "workspace/notes/plan.md"}


@pytest.mark.parametrize("name", [
    "../outside.txt",
    "workspace/../../outside.txt",
    "C:/Windows/win.ini",
    "\\\\server\\share\\file.txt",
    "config/mcp_servers.json",
    "database/unexpected.sql",
])
def test_backup_archive_rejects_unsafe_or_unrecognized_entries(tmp_path, name):
    archive = _archive(tmp_path, [
        ("manifest.json", json.dumps({"format": "aura-desktop-backup", "format_version": 1})),
        ("database/aura.dump", b"pgdump"),
        (name, b"not allowed"),
    ])
    with archive:
        with pytest.raises(RuntimeError):
            _checked_members(archive)


def test_backup_archive_rejects_case_insensitive_duplicate_paths(tmp_path):
    archive = _archive(tmp_path, [
        ("manifest.json", json.dumps({"format": "aura-desktop-backup", "format_version": 1})),
        ("database/aura.dump", b"pgdump"),
        ("workspace/Plan.md", b"one"),
        ("workspace/plan.md", b"two"),
    ])
    with archive:
        with pytest.raises(RuntimeError, match="duplicate"):
            _checked_members(archive)


def test_backup_archive_rejects_symbolic_links(tmp_path):
    archive_path = tmp_path / "backup.aurabackup"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "aura-desktop-backup", "format_version": 1}))
        archive.writestr("database/aura.dump", b"pgdump")
        link = zipfile.ZipInfo("workspace/external")
        link.create_system = 3
        link.external_attr = (0o120777 << 16) | 0o777
        archive.writestr(link, "../../outside")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(RuntimeError, match="symbolic link"):
            _checked_members(archive)


def test_backup_archive_rejects_compressed_members(tmp_path):
    archive_path = tmp_path / "backup.aurabackup"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "aura-desktop-backup", "format_version": 1}))
        archive.writestr("database/aura.dump", b"pgdump", compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(RuntimeError, match="compression"):
            _checked_members(archive)
