# Local SQLite backup and restore

The default local configuration stores application data in a SQLite database,
LangGraph checkpoints in a second SQLite database, and sandbox files under the
configured workspace root. `scripts/backup_local.py` captures all three in one
checksummed archive. It supports only file-backed SQLite `DATABASE_URL` values;
PostgreSQL deployments should use the Compose backup procedure instead.
Run the commands from the repository root so relative `.env`, database, and
checkpoint paths resolve the same way they do when AURA is started there.

Stop every local AURA API/worker process that can write these stores before
creating or restoring an archive. The command requires `--api-stopped` as an
explicit confirmation. It snapshots both SQLite databases through SQLite's
online backup API, archives regular workspace files and directories, and
verifies the finished archive. Symbolic links and special files are rejected.
Choose a backup path outside the database, checkpoint, and workspace paths.

```powershell
python scripts/backup_local.py .\backups\aura-local.tar.gz --api-stopped
python scripts/backup_local.py --verify .\backups\aura-local.tar.gz
```

Restoring replaces the current SQLite databases and workspace contents. Stop
all AURA processes first. Both confirmations are required, and the backup is
fully verified (including SQLite integrity checks) before the script changes
current files. Make a separate backup first if the existing local state must
also be kept:

```powershell
python scripts/backup_local.py --restore .\backups\aura-local.tar.gz --api-stopped --replace-current-data
```

The archive contains personal data. Store it with access controls and
encryption appropriate for that data. The local API and Compose backup
archives are separate formats and use their corresponding scripts.
