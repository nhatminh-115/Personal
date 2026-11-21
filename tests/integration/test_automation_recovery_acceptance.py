"""A4 webhook approval and run history must survive an API process restart."""

from pathlib import Path

import pytest

from scripts.dogfood_automation_recovery import (
    CALLER_SENTINEL,
    MARKER_CONTENT,
    SAVED_INSTRUCTION,
    run_acceptance,
)


@pytest.mark.asyncio
async def test_automation_webhook_duplicate_and_approval_survive_process_restart(tmp_path: Path):
    report_dir = tmp_path / "reports"
    report = await run_acceptance(
        state_dir=tmp_path / "isolated-state",
        report_dir=report_dir,
    )

    assert report["outcome"] == "PASS"
    assert report["execution"]["mode"] == "isolated_local_api_processes"
    assert report["execution"]["model_provider"] == "mock"
    assert report["execution"]["live_inference_claim"] is False
    assert report["execution"]["service_restart_count"] == 1
    assert len(report["entities"]["event_id"]) == 36
    assert len(report["entities"]["run_id"]) == 36
    assert len(report["entities"]["approval_id"]) == 36
    assert report["route"]["provider"] == "mock"
    assert report["route"]["privacy_policy"] == "local_only"
    assert report["route"]["fallback_policy"] == "local_only"
    assert report["cancellation"]["status"] == "cancelled"
    assert {
        "duplicate_webhook_delivery_reuses_original_event",
        "consequential_workspace_write_waits_for_approval",
        "approval_paused_run_and_history_survive_api_restart",
        "approved_run_resumes_and_completes_after_restart",
        "queued_automation_run_can_be_cancelled_and_retained_in_history",
        "webhook_secret_is_persisted_as_digest_only",
        "webhook_body_is_ignored_and_not_persisted",
    } <= {item["name"] for item in report["assertions"]}
    assert {
        "automation_triggered",
        "routing_profile_resolved",
        "model_selected",
        "approval_requested",
        "run_completed",
        "outbox_event_processed",
    } <= {event["event_type"] for event in report["events"]}

    serialized = (report_dir / report["report_file"]).read_text(encoding="utf-8")
    assert SAVED_INSTRUCTION not in serialized
    assert CALLER_SENTINEL not in serialized
    assert MARKER_CONTENT not in serialized
