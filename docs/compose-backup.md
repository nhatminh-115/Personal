# Docker Compose backup and restore

AURA stores application data in PostgreSQL and LangGraph checkpoints in a
separate SQLite database. A recoverable run needs both stores from the same
point in time. The backup command stops `aura-app` while it captures both,
then restarts it if it was running before the backup.

From the repository root, create a new archive:

```powershell
python scripts/backup_compose.py .\backups\aura-2026-10-03.tar.gz
```

The target must not already exist. The archive contains a PostgreSQL custom
dump, the checkpoint database and optional SQLite WAL, and a manifest with
SHA-256 checksums. Verify an archive before restoring it:

```powershell
python scripts/backup_compose.py --verify .\backups\aura-2026-10-03.tar.gz
New-Item -ItemType Directory -Force .\restore | Out-Null
tar -xzf .\backups\aura-2026-10-03.tar.gz -C .\restore
```

Restore with the same Compose configuration and database name used to create
the backup. These commands replace the current database and checkpoint state;
make a separate backup first if the current state needs to be retained.

```powershell
docker compose stop --timeout 30 aura-app
docker compose cp .\restore\postgres.dump postgres:/tmp/aura-postgres.dump
docker compose exec -T --user 0 postgres chmod 644 /tmp/aura-postgres.dump
docker compose exec -T postgres pg_restore --clean --if-exists --no-owner -U aura -d aura /tmp/aura-postgres.dump
docker compose exec -T aura-app sh -c 'rm -f /app/checkpoints/aura_checkpoints.db-wal /app/checkpoints/aura_checkpoints.db-shm'
docker compose cp .\restore\checkpoint\aura_checkpoints.db aura-app:/app/checkpoints/aura_checkpoints.db
if (Test-Path .\restore\checkpoint\aura_checkpoints.db-wal) {
  docker compose cp .\restore\checkpoint\aura_checkpoints.db-wal aura-app:/app/checkpoints/aura_checkpoints.db-wal
}
docker compose exec -T --user 0 aura-app chown -R aurauser:aurauser /app/checkpoints/aura_checkpoints.db*
docker compose start aura-app
```

Keep the API stopped until both stores have been restored. If a restore command
fails, leave it stopped and resolve the error before starting it. Backups
contain personal workspace data and should be stored with access controls and
encryption appropriate for that data.
