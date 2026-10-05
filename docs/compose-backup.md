# Docker Compose backup and restore

AURA stores application data in PostgreSQL, LangGraph checkpoints in a
separate SQLite database, and sandbox/workspace files in the `workspace_data`
volume. A recoverable installation needs all three from the same point in time.
The backup command stops `aura-app` while it captures them,
then restarts it if it was running before the backup.
Before reporting success, the command reopens the completed archive and checks
its manifest and payload hashes. If capture, verification, or API shutdown
fails, it removes any partial output and attempts to restore the API's original
running state.

From the repository root, create a new archive:

```powershell
python scripts/backup_compose.py .\backups\aura-2026-10-03.tar.gz
```

The target must not already exist. The archive contains a PostgreSQL custom
dump, the checkpoint database and optional SQLite WAL, a compressed snapshot of
the workspace volume, and a manifest with SHA-256 checksums. Verification also
rejects unsafe workspace archive paths, links, and special files. Verify an
archive before restoring it:

```powershell
python scripts/backup_compose.py --verify .\backups\aura-2026-10-03.tar.gz
```

List the archive files in a backup directory and verify each one without
extracting or changing it:

```powershell
python scripts/backup_compose.py --list .\backups
```

The command reports each archive as `VERIFIED` or `INVALID` and returns a
nonzero exit code if any archive failed verification. It does not delete or
repair invalid files.

Restore with the same Compose configuration and database name used to create
the backup. The restore command verifies the archive again before it stops
services, then replaces PostgreSQL, the checkpoint database, and workspace
files as one recovery operation. Workspace replacement stages the restored
files inside the volume and rolls the old files back if the replacement fails.
The required flag makes that
replacement explicit; make a separate backup first if the current state needs
to be retained.

Older format-version 1 archives remain verifiable and can restore PostgreSQL
and checkpoints, but they contain no workspace snapshot and therefore leave
the current workspace volume untouched. Create a version 2 archive to recover
all three stores.

```powershell
python scripts/restore_compose.py .\backups\aura-2026-10-03.tar.gz --replace-current-data
```

If restore fails after the API stops, the command leaves it stopped so it cannot
write against partially restored state. Resolve the error and rerun the
verified restore before starting AURA. The command preserves the API's original
running/stopped state after a successful restore. Backups contain personal
workspace data and should be stored with access controls and encryption
appropriate for that data.
