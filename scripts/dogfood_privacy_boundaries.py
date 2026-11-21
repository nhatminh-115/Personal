"""Run A5 privacy-boundary acceptance checks and write a sanitized report.

All provider-facing calls use deterministic spies. The report records identifiers
and routing metadata only; prompts, file text, provider responses, and credentials
are never included.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "tests/unit/test_model_router.py::test_explicit_provider_route_blocks_cloud_before_provider_call",
    "tests/unit/test_embedding_abstraction.py::test_cloud_embedding_calls_are_blocked_before_provider_invocation",
    "tests/unit/test_composite_provider.py::test_search_tool_blocks_external_query_for_strict_privacy",
    "tests/unit/test_capability_providers.py::test_strict_privacy_filters_cloud_and_unknown_capability_providers",
    "tests/unit/test_workspace_graph.py::test_project_memory_local_only_blocks_cloud_model_before_provider_call",
    "tests/unit/test_workspace_graph.py::test_session_local_only_episode_blocks_cloud_model_before_provider_call",
    "tests/unit/test_workspace_graph.py::test_profile_local_only_blocks_cloud_model_before_provider_call",
    "tests/unit/test_workspace_graph.py::test_project_scoped_semantic_local_only_blocks_cloud_model_before_provider_call",
    "tests/unit/test_workspace_graph.py::test_confidential_context_never_exposes_cloud_capability_tools",
    "tests/integration/test_api_routes.py::test_explicit_local_file_text_requires_cloud_confirmation_and_stays_out_of_trace",
    "tests/integration/test_routing_confirmation_flow.py::test_rejected_routing_confirmation_never_calls_model",
    "tests/integration/test_routing_confirmation_flow.py::test_approved_routing_confirmation_resumes_same_run",
]
SOURCE_FILES = [
    "app/models/router.py",
    "tests/unit/test_model_router.py",
    "tests/unit/test_embedding_abstraction.py",
    "tests/integration/test_api_routes.py",
    "scripts/dogfood_privacy_boundaries.py",
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_sha256() -> str:
    digest = hashlib.sha256()
    for relative_path in SOURCE_FILES:
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((REPOSITORY_ROOT / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_report(output_path: Path, api_evidence: dict, started_at: str, pytest_output: str) -> None:
    summary = re.search(r"(\d+ passed(?:, \d+ skipped)?)(?: in ([\d.]+)s)?", pytest_output)
    if not summary:
        raise RuntimeError("Acceptance test summary was not found.")

    assertions = [
        {
            "name": "cloud_model_blocked_before_provider_invocation_for_strict_privacy",
            "result": "PASS",
            "evidence": [TESTS[0], *TESTS[4:8]],
        },
        {
            "name": "cloud_embedding_batch_and_query_blocked_before_provider_invocation",
            "result": "PASS",
            "evidence": [TESTS[1]],
        },
        {
            "name": "external_research_search_blocked_before_provider_invocation",
            "result": "PASS",
            "evidence": [TESTS[2]],
        },
        {
            "name": "cloud_capability_filtered_before_tool_or_model_invocation",
            "result": "PASS",
            "evidence": [TESTS[3], TESTS[8]],
        },
        *api_evidence["assertions"],
        {
            "name": "routing_confirmation_rejection_never_calls_model",
            "result": "PASS",
            "evidence": [TESTS[10]],
        },
        {
            "name": "approved_confirmation_resumes_through_the_same_run",
            "result": "PASS",
            "evidence": [TESTS[11]],
        },
    ]
    report = {
        "schema_version": 1,
        "scenario": "A5_privacy_boundary",
        "outcome": "PASS",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "execution": {
            "mode": "local_pytest_api_and_provider_spies",
            "live_inference_claim": False,
            "external_provider_invocations": 0,
            "pytest_summary": summary.group(1),
            "pytest_duration_seconds": float(summary.group(2)) if summary.group(2) else None,
        },
        "run_id": api_evidence["run_id"],
        "confirmation_id": api_evidence["confirmation_id"],
        "events": api_evidence["events"],
        "route": api_evidence["route"],
        "assertions": assertions,
        "source": {
            "base_commit_sha": _git_revision(),
            "acceptance_source_sha256": _source_sha256(),
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "docs/acceptance/a5-privacy-boundary-20261121.json",
    )
    args = parser.parse_args()
    output_path = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output

    started_at = _utc_now()
    with tempfile.TemporaryDirectory(prefix="aura-a5-") as temp_dir:
        api_evidence_path = Path(temp_dir) / "api-evidence.json"
        environment = os.environ.copy()
        environment["AURA_A5_REPORT_PATH"] = str(api_evidence_path)
        command = [sys.executable, "-m", "pytest", "-q", *TESTS]
        result = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        if result.returncode != 0:
            print("A5 ACCEPTANCE RESULT: FAIL", file=sys.stderr)
            return result.returncode
        if not api_evidence_path.is_file():
            print("A5 ACCEPTANCE RESULT: FAIL (missing sanitized API evidence)", file=sys.stderr)
            return 1

        try:
            api_evidence = json.loads(api_evidence_path.read_text(encoding="utf-8"))
            _write_report(output_path, api_evidence, started_at, result.stdout + result.stderr)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"A5 ACCEPTANCE RESULT: FAIL ({type(exc).__name__})", file=sys.stderr)
            return 1

    print(f"A5 ACCEPTANCE RESULT: PASS ({output_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
