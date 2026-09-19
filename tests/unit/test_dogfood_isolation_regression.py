"""Deterministic regression tests for dogfood runtime isolation and import safety.

Verifies:
1. Importing scripts.dogfood_research_live does NOT mutate DATABASE_URL or CHECKPOINT_DB_PATH.
2. After dogfood runtime configuration:
   - active SQLAlchemy engine URL points to aura_dogfood_live.db
   - active checkpointer path points to aura_dogfood_live_checkpoints.db
   - existing/default AURA database (aura.db / aura_checkpoints.db) is NOT used
   - schema and checkpoint storage are created exclusively in isolated files
"""

import os
from pathlib import Path
import subprocess
import sys
import pytest
from sqlalchemy import text


def test_import_dogfood_script_does_not_mutate_environment():
    """Importing scripts.dogfood_research_live alone must NOT mutate environment variables."""
    # Run in an isolated subprocess to test fresh import without prior loaded modules
    code = (
        "import os, sys\n"
        "os.environ.pop('DATABASE_URL', None)\n"
        "os.environ.pop('CHECKPOINT_DB_PATH', None)\n"
        "import scripts.dogfood_research_live\n"
        "assert 'DATABASE_URL' not in os.environ, f'DATABASE_URL mutated: {os.environ.get(\"DATABASE_URL\")}'\n"
        "assert 'CHECKPOINT_DB_PATH' not in os.environ, f'CHECKPOINT_DB_PATH mutated: {os.environ.get(\"CHECKPOINT_DB_PATH\")}'\n"
        "print('IMPORT_ISOLATION_SAFE')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(".").resolve()),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Import safety failed:\nStdout: {result.stdout}\nStderr: {result.stderr}"
    assert "IMPORT_ISOLATION_SAFE" in result.stdout


@pytest.mark.asyncio
async def test_dogfood_runtime_isolation_configured_paths():
    """Dogfood runtime initialization must configure active engine and checkpointer to isolated paths."""
    from scripts.dogfood_research_live import (
        DOGFOOD_CHECKPOINT_DB_PATH,
        DOGFOOD_DATABASE_URL,
        configure_dogfood_runtime,
    )
    from app.core.settings import settings
    from app.db import session as db_session
    from app.orchestrator.graph import (
        close_checkpointer,
        get_active_checkpointer_path,
        init_checkpointer,
    )

    # Save original state for teardown
    orig_env_db = os.environ.get("DATABASE_URL")
    orig_env_cp = os.environ.get("CHECKPOINT_DB_PATH")
    orig_settings_db = settings.DATABASE_URL
    orig_settings_cp = settings.CHECKPOINT_DB_PATH

    dogfood_db_file = Path("aura_dogfood_live.db")
    dogfood_cp_file = Path("aura_dogfood_live_checkpoints.db")

    try:
        # 1. Execute runtime configuration
        configure_dogfood_runtime()

        # 2. Assert environment variables match dogfood isolation paths
        assert os.environ.get("DATABASE_URL") == DOGFOOD_DATABASE_URL
        assert os.environ.get("CHECKPOINT_DB_PATH") == DOGFOOD_CHECKPOINT_DB_PATH

        # 3. Assert settings singleton points to dogfood paths
        assert settings.DATABASE_URL == DOGFOOD_DATABASE_URL
        assert settings.CHECKPOINT_DB_PATH.name == "aura_dogfood_live_checkpoints.db"

        # 4. Assert active SQLAlchemy engine URL points to aura_dogfood_live.db
        active_engine_url = str(db_session.engine.url)
        assert active_engine_url.endswith("aura_dogfood_live.db"), f"Unexpected engine URL: {active_engine_url}"
        assert active_engine_url != "sqlite+aiosqlite:///aura.db", "Default aura.db engine was not replaced!"

        # 5. Initialize checkpointer and assert active path points to aura_dogfood_live_checkpoints.db
        await init_checkpointer()
        active_cp_path = get_active_checkpointer_path()
        assert active_cp_path is not None, "Checkpointer path was not recorded"
        assert active_cp_path.endswith("aura_dogfood_live_checkpoints.db"), (
            f"Unexpected checkpointer path: {active_cp_path}"
        )
        assert not active_cp_path.endswith("aura_checkpoints.db") or "dogfood_live" in active_cp_path

        # 6. Verify database initialization operates against the isolated DB
        await db_session.init_db()
        assert dogfood_db_file.exists(), "Isolated aura_dogfood_live.db was not created on init_db()"

        # Verify tables are usable in isolated DB
        async with db_session.async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

        # Verify checkpointer file exists
        assert dogfood_cp_file.exists(), "Isolated aura_dogfood_live_checkpoints.db was not created"

    finally:
        # Graceful cleanup
        await close_checkpointer()
        await db_session.engine.dispose()

        # Remove created dogfood test files
        for f in [dogfood_db_file, dogfood_cp_file]:
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass

        # Restore original environment and engine
        if orig_env_db is not None:
            os.environ["DATABASE_URL"] = orig_env_db
        else:
            os.environ.pop("DATABASE_URL", None)

        if orig_env_cp is not None:
            os.environ["CHECKPOINT_DB_PATH"] = orig_env_cp
        else:
            os.environ.pop("CHECKPOINT_DB_PATH", None)

        settings.DATABASE_URL = orig_settings_db
        settings.CHECKPOINT_DB_PATH = orig_settings_cp
        db_session.configure_engine(orig_settings_db)
