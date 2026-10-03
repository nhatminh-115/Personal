# Docker Compose backup and restore

AURA stores application data in PostgreSQL and LangGraph checkpoints in a
separate SQLite database. A recoverable run needs both stores from the same
point in time. The backup command stops `aura-app` while it captures both,
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
dump, the checkpoint database and optional SQLite WAL, and a manifest with
SHA-256 checksums. Verify an archive before restoring it:

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
services, then replaces PostgreSQL and the checkpoint database as one recovery
operation. The required flag makes that replacement explicit; make a separate
backup first if the current state needs to be retained.

```powershell
python scripts/restore_compose.py .\backups\aura-2026-10-03.tar.gz --replace-current-data
```

If restore fails after the API stops, the command leaves it stopped so it cannot
write against partially restored state. Resolve the error and rerun the
verified restore before starting AURA. The command preserves the API's original
running/stopped state after a successful restore. Backups contain personal
workspace data and should be stored with access controls and encryption
appropriate for that data.
