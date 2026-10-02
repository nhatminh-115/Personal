import os
import tempfile
import pytest
from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, inspect, text

def test_alembic_upgrade_downgrade_cycle():
    """Test full Alembic migration cycle from base to head and back to base."""
    # Create temporary SQLite database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        # Construct synchronous and async SQLite URLs
        sync_url = f"sqlite:///{db_path.replace(chr(92), '/')}"
        async_url = f"sqlite+aiosqlite:///{db_path.replace(chr(92), '/')}"

        # Set up alembic config
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", async_url)

        # Upgrade to the previous head and simulate legacy duplicate defaults.
        command.upgrade(alembic_cfg, "010_workspace_object_graph")
        engine = create_engine(sync_url)
        with engine.begin() as connection:
            for profile_id, is_active, updated_at in (
                ("legacy-default-a", True, "2026-09-01 00:00:00"),
                ("legacy-default-z", True, "2026-09-02 00:00:00"),
                ("legacy-default-inactive", False, "2026-09-03 00:00:00"),
            ):
                connection.execute(text("""
                    INSERT INTO routing_profiles (
                        id, name, version, is_active, is_default,
                        global_privacy_policy, global_fallback_policy,
                        cost_preference, latency_preference, routes_json,
                        created_at, updated_at
                    ) VALUES (
                        :id, :name, 1, :is_active, 1, 'internal', 'none',
                        'normal', 'normal', '{}', :updated_at, :updated_at
                    )
                """), {"id": profile_id, "name": profile_id, "is_active": is_active, "updated_at": updated_at})
        engine.dispose()

        # The next migration normalizes old data before enforcing uniqueness.
        command.upgrade(alembic_cfg, "head")

        # 2. Inspect created schema using a sync engine
        engine = create_engine(sync_url)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        expected_tables = {
            "sessions",
            "messages",
            "runs",
            "run_events",
            "approvals",
            "memories",
            "events",
            "scheduled_jobs",
            "delegations",
            "alembic_version",
            "workspace_objects",
            "workspace_edges",
            "workspace_object_project_links",
        }
        assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"

        message_columns = {
            col["name"]: col for col in inspector.get_columns("messages")
        }
        assert message_columns["metadata_json"]["nullable"] is False

        workspace_object_columns = {
            col["name"]: col for col in inspector.get_columns("workspace_objects")
        }
        assert workspace_object_columns["project_name"]["nullable"] is True
        workspace_link_columns = {
            col["name"] for col in inspector.get_columns("workspace_object_project_links")
        }
        assert workspace_link_columns == {"object_id", "project_name", "created_at"}

        # Check delegations index
        delegation_indexes = {idx["name"] for idx in inspector.get_indexes("delegations")}
        assert "uq_delegations_parent_call" in delegation_indexes, f"Missing unique index on delegations: {delegation_indexes}"

        # Check events columns
        event_cols = {col["name"] for col in inspector.get_columns("events")}
        expected_event_cols = {
            "id",
            "event_type",
            "source",
            "payload_json",
            "status",
            "occurred_at",
            "processed_at",
            "correlation_id",
            "retry_count",
            "error_message",
            "idempotency_key",
            "max_attempts",
            "next_attempt_at",
            "locked_at",
            "locked_by",
        }
        assert expected_event_cols.issubset(event_cols), f"Missing events columns: {expected_event_cols - event_cols}"
        event_indexes = {idx["name"] for idx in inspector.get_indexes("events")}
        assert "uq_events_idempotency_key" in event_indexes, f"Missing unique index on events: {event_indexes}"

        routing_indexes = {idx["name"] for idx in inspector.get_indexes("routing_profiles")}
        assert "uq_routing_profiles_single_default" in routing_indexes
        with engine.connect() as connection:
            defaults = connection.execute(text(
                "SELECT id FROM routing_profiles WHERE is_default = TRUE"
            )).scalars().all()
        assert defaults == ["legacy-default-z"]

        # The full downgrade cycle exercises old routing migrations whose
        # SQLite ALTER TABLE steps predate safe defaults for populated tables.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM routing_profiles"))

        # Check scheduled_jobs columns
        job_cols = {col["name"] for col in inspector.get_columns("scheduled_jobs")}
        expected_job_cols = {"id", "name", "job_type", "locked_at", "locked_by", "next_run_at"}
        assert expected_job_cols.issubset(job_cols), f"Missing scheduled_jobs columns: {expected_job_cols - job_cols}"

        # Check memories columns
        memory_cols = {col["name"] for col in inspector.get_columns("memories")}
        expected_mem_cols = {
            "embedding_model",
            "embedding_dim",
            "project_name",
            "confidence",
            "is_active",
            "supersedes_id",
            "superseded_by_id",
        }
        assert expected_mem_cols.issubset(memory_cols), f"Missing memories columns: {expected_mem_cols - memory_cols}"

        # Check approvals columns
        approval_cols = {col["name"] for col in inspector.get_columns("approvals")}
        assert "tool_call_id" in approval_cols

        engine.dispose()

        # 3. Test downgrade to base
        command.downgrade(alembic_cfg, "base")

        engine = create_engine(sync_url)
        inspector = inspect(engine)
        remaining_tables = set(inspector.get_table_names()) - {"alembic_version"}
        assert len(remaining_tables) == 0, f"Tables remained after downgrade: {remaining_tables}"
        engine.dispose()

        # 4. Test re-upgrade head
        command.upgrade(alembic_cfg, "head")
        engine = create_engine(sync_url)
        inspector = inspect(engine)
        reupgraded_tables = set(inspector.get_table_names())
        assert expected_tables.issubset(reupgraded_tables)
        engine.dispose()

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
