"""A1 project continuity must survive a complete API process restart."""

from pathlib import Path

import pytest

from scripts.dogfood_project_continuity import run_acceptance


@pytest.mark.asyncio
async def test_project_note_context_and_provenance_survive_process_restart(tmp_path: Path):
    report = await run_acceptance(
        state_dir=tmp_path / "isolated-state",
        report_dir=tmp_path / "reports",
    )

    assert report["outcome"] == "PASS"
    assert report["execution"]["mode"] == "isolated_local_api_processes"
    assert report["execution"]["model_provider"] == "mock"
    assert report["execution"]["live_inference_claim"] is False
    assert report["execution"]["service_restart_count"] == 1
    assert len(report["source"]["base_commit_sha"]) == 40
    assert len(report["source"]["runner_sha256"]) == 64
    assert report["route"]["provider"] == "mock"
    assert report["reopened_workspace"]["project_note_count"] == 1
    assert report["persisted_context"]["foreign_note_excluded"] is True
    assert {
        event["event_type"] for event in report["events"]
    } >= {"routing_profile_resolved", "model_selected", "context_compiled"}

    serialized = (tmp_path / "reports" / report["report_file"]).read_text(encoding="utf-8")
    assert "Synthetic A1 continuity marker" not in serialized
    assert "Synthetic foreign-project decoy" not in serialized
    assert "Use only the selected project note" not in serialized
