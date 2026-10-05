"""Regression checks for research dogfood isolation, import safety, and approval handling."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import text


def test_import_dogfood_script_does_not_mutate_environment():
    code = (
        "import os, sys\n"
        "os.environ.pop('DATABASE_URL', None)\n"
        "os.environ.pop('CHECKPOINT_DB_PATH', None)\n"
        "import scripts.dogfood_research_live\n"
        "assert 'DATABASE_URL' not in os.environ\n"
        "assert 'CHECKPOINT_DB_PATH' not in os.environ\n"
        "print('IMPORT_ISOLATION_SAFE')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(".").resolve()),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Import safety failed:\n{result.stdout}\n{result.stderr}"
    assert "IMPORT_ISOLATION_SAFE" in result.stdout


@pytest.mark.asyncio
async def test_dogfood_runtime_uses_unique_run_paths_and_preserves_prior_evidence(tmp_path):
    from scripts.dogfood_research_live import configure_dogfood_runtime
    from app.core.settings import settings
    from app.db import session as db_session
    from app.orchestrator.graph import close_checkpointer, get_active_checkpointer_path, init_checkpointer

    orig_env_db = os.environ.get("DATABASE_URL")
    orig_env_cp = os.environ.get("CHECKPOINT_DB_PATH")
    orig_settings_db = settings.DATABASE_URL
    orig_settings_cp = settings.CHECKPOINT_DB_PATH
    orig_settings_model_provider = settings.MODEL_PROVIDER
    prior_db = tmp_path / "research-older-run.db"
    prior_checkpoints = tmp_path / "research-older-run-checkpoints.db"
    configure_dogfood_runtime("older-run", state_dir=tmp_path)
    prior_db.write_text("prior database evidence", encoding="utf-8")
    prior_checkpoints.write_text("prior checkpoint evidence", encoding="utf-8")
    dogfood_db = tmp_path / "research-current-run.db"
    dogfood_checkpoints = tmp_path / "research-current-run-checkpoints.db"

    try:
        database_url, checkpoint_path = configure_dogfood_runtime("current-run", state_dir=tmp_path)
        assert os.environ["DATABASE_URL"] == database_url
        assert os.environ["CHECKPOINT_DB_PATH"] == str(dogfood_checkpoints)
        assert settings.DATABASE_URL == database_url
        assert settings.CHECKPOINT_DB_PATH == dogfood_checkpoints
        assert settings.MODEL_PROVIDER == orig_settings_model_provider
        assert str(db_session.engine.url).endswith("research-current-run.db")
        assert not database_url.endswith("aura.db")

        await init_checkpointer()
        active_path = get_active_checkpointer_path()
        assert active_path == str(dogfood_checkpoints)
        await db_session.init_db()
        assert dogfood_db.exists()
        async with db_session.async_session_factory() as session:
            assert (await session.execute(text("SELECT 1"))).scalar() == 1
        assert dogfood_checkpoints.exists()

        assert prior_db.read_text(encoding="utf-8") == "prior database evidence"
        assert prior_checkpoints.read_text(encoding="utf-8") == "prior checkpoint evidence"
        assert database_url != "sqlite+aiosqlite:///aura_dogfood_live.db"
    finally:
        await close_checkpointer()
        await db_session.engine.dispose()
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
        settings.MODEL_PROVIDER = orig_settings_model_provider
        db_session.configure_engine(orig_settings_db)


def test_pending_approval_is_recorded_without_submitting_a_decision(tmp_path):
    from scripts.dogfood_research_live import pending_approval_report, write_pending_approval_report

    report = pending_approval_report("run-123", "approval-456")
    assert report == {
        "scenario": "research_live_dogfood",
        "run_id": "run-123",
        "status": "waiting_for_approval",
        "approval_id": "approval-456",
        "approval_decision_submitted": False,
    }
    path = write_pending_approval_report("run-123", "approval-456", output_dir=tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == report
