"""Unit tests for deterministic task and model routing policy (Milestone 3B)."""

import pytest
from app.models.base import ChatMessage, ModelRequest, ModelRole, RoutingContext
from app.models.mock_provider import MockModelProvider
from app.models.router import ModelRouter
from app.models.routing_policy import (
    DeterministicRoutingPolicy,
    ProviderMetadata,
)


@pytest.fixture
def sample_metadata():
    return {
        "cloud-standard": ProviderMetadata(
            name="cloud-standard",
            capabilities=["general"],
            privacy_status="cloud",
            cost_class="low",
            latency_class="low",
            default_model="cloud-std-v1",
        ),
        "cloud-smart": ProviderMetadata(
            name="cloud-smart",
            capabilities=["general", "reasoning"],
            privacy_status="cloud",
            cost_class="high",
            latency_class="medium",
            default_model="cloud-smart-o1",
        ),
        "code-specialist": ProviderMetadata(
            name="code-specialist",
            capabilities=["code", "general"],
            privacy_status="cloud",
            cost_class="medium",
            latency_class="medium",
            default_model="deepseek-coder",
        ),
        "local-ollama": ProviderMetadata(
            name="local-ollama",
            capabilities=["general", "code", "fast", "local"],
            privacy_status="local",
            cost_class="low",
            latency_class="low",
            default_model="llama3-local",
        ),
    }


def test_fallback_routing_when_context_is_empty(sample_metadata):
    policy = DeterministicRoutingPolicy()
    sel = policy.select(context=None, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "cloud-standard"
    assert sel.model_name == "cloud-std-v1"
    assert "No routing context provided" in sel.reason


def test_explicit_override_routing(sample_metadata):
    policy = DeterministicRoutingPolicy()

    # Provider override only
    ctx1 = RoutingContext(explicit_model_override="local-ollama")
    sel1 = policy.select(context=ctx1, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel1.provider_name == "local-ollama"
    assert sel1.model_name == "llama3-local"
    assert "Explicit provider override" in sel1.reason

    # Provider + Model override
    ctx2 = RoutingContext(explicit_model_override="cloud-smart:custom-checkpoint")
    sel2 = policy.select(context=ctx2, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel2.provider_name == "cloud-smart"
    assert sel2.model_name == "custom-checkpoint"
    assert "Explicit model override" in sel2.reason


def test_privacy_confidential_routing(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(
        task_type="coding",
        privacy_requirement="confidential",
    )
    sel = policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "local-ollama"
    assert "Confidential privacy requirement" in sel.reason


def test_coding_task_routing(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(task_type="coding")
    sel = policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "code-specialist"
    assert sel.model_name == "deepseek-coder"
    assert "Coding task matched" in sel.reason


def test_complex_reasoning_routing(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(complexity="complex")
    sel = policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "cloud-smart"
    assert sel.model_name == "cloud-smart-o1"
    assert "High complexity matched" in sel.reason


@pytest.mark.asyncio
async def test_router_select_model_and_tracing(test_db_session):
    from app.observability.tracer import TraceService
    trace_service = TraceService(test_db_session)

    router = ModelRouter()
    mock_prov = MockModelProvider(default_response="Routed response")
    router.register_provider(
        mock_prov,
        ProviderMetadata(
            name="mock",
            capabilities=["general", "code", "reasoning"],
            privacy_status="local",
            default_model="mock-v1",
        ),
    )

    ctx = RoutingContext(
        task_type="coding",
        run_id="run-route-test-123",
        session_id="session-route-123",
    )

    provider, selection = router.select_model_for_task(ctx)
    assert selection.provider_name == "mock"
    assert selection.model_name == "mock-v1"
    assert "Coding task matched" in selection.reason

    # Record trace event using TraceService
    await trace_service.record_event(
        run_id="run-route-test-123",
        session_id="session-route-123",
        event_type="model_called",
        payload={
            "routing_decision": {
                "provider": selection.provider_name,
                "model": selection.model_name,
                "reason": selection.reason,
            }
        },
    )

    events = await trace_service.get_run_events("run-route-test-123")
    assert len(events) == 1
    assert events[0].event_type == "model_called"
    assert events[0].payload["routing_decision"]["provider"] == "mock"
    assert events[0].payload["routing_decision"]["model"] == "mock-v1"
