"""Deterministic preflight checks for the live research dogfood."""

from scripts.dogfood_research_live import (
    RESEARCH_WORKLOAD,
    _chat_request_payload,
    dogfood_acceptance_failures,
    live_environment_error,
)


def test_live_research_requires_live_mode_and_non_mock_router():
    assert "RESEARCH_PROVIDER_MODE=live" in live_environment_error({"MODEL_PROVIDER": "openai"})
    assert "MODEL_PROVIDER=openai" in live_environment_error({
        "MODEL_PROVIDER": "mock",
        "OPENAI_API_KEY": "configured",
        "RESEARCH_PROVIDER_MODE": "live",
    })
    assert "OPENAI_API_KEY or an explicit loopback Ollama override" in live_environment_error({
        "MODEL_PROVIDER": "openai",
        "RESEARCH_PROVIDER_MODE": "live",
    })


def test_live_research_allows_exact_local_ollama_only_on_loopback():
    local = {
        "MODEL_PROVIDER": "openai",
        "RESEARCH_PROVIDER_MODE": "live",
        "AURA_DOGFOOD_MODEL_OVERRIDE": "ollama:aura-qwen3-coding:4b-8k",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434/v1",
    }
    assert live_environment_error(local) is None
    assert "exact ollama:model" in live_environment_error({
        **local, "AURA_DOGFOOD_MODEL_OVERRIDE": "ollama: "
    })
    assert "loopback" in live_environment_error({
        **local, "OLLAMA_BASE_URL": "https://models.example.com"
    })


def test_research_chat_request_carries_exact_local_lock_and_delegation_prompt():
    request = _chat_request_payload("session-1", "project", {
        "AURA_DOGFOOD_MODEL_OVERRIDE": "ollama:aura-qwen3-coding:4b-8k",
    })
    assert request["model_override"] == "ollama:aura-qwen3-coding:4b-8k"
    assert request["reasoning_override"] == "instant"
    assert "delegate_task with specialist_name='research'" in request["message"]
    assert "delegate_task with specialist_name='research'" in RESEARCH_WORKLOAD


def test_research_dogfood_rejects_insufficient_evidence_as_non_acceptance():
    failures = dogfood_acceptance_failures({
        "specialist_name": "research",
        "delegation_status": "completed",
        "child_run_status": "completed",
        "actual_model_provider": "ollama",
        "actual_model_name": "aura-qwen3-coding:4b-8k",
        "model_call_count": 1,
        "tool_sequence": ["research_search"],
        "research_state_status": "running",
        "sources_count": 0,
        "inspected_count": 0,
        "evidence_count": 0,
        "source_supported_claim_count": 0,
        "provenance_memory_count": 0,
    })
    assert "checkpointed research did not complete (status: running)" in failures
    assert "required research tool was not recorded: extract_evidence" in failures
    assert "no verified source-supported claim was persisted" in failures
    assert "no claim/evidence-linked project memory was persisted" in failures


def test_research_dogfood_accepts_complete_provenance_chain():
    report = {
        "specialist_name": "research",
        "delegation_status": "completed",
        "child_run_status": "completed",
        "actual_model_provider": "ollama",
        "actual_model_name": "aura-qwen3-coding:4b-8k",
        "model_call_count": 1,
        "tool_sequence": ["research_search", "extract_evidence", "record_research_claim"],
        "research_state_status": "completed",
        "sources_count": 1,
        "inspected_count": 1,
        "evidence_count": 1,
        "source_supported_claim_count": 1,
        "provenance_memory_count": 1,
    }
    assert dogfood_acceptance_failures(report) == []
