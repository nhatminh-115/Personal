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
            models=["cloud-std-v1", "cloud-std-v2"],
        ),
        "cloud-smart": ProviderMetadata(
            name="cloud-smart",
            capabilities=["general", "reasoning"],
            privacy_status="cloud",
            cost_class="high",
            latency_class="medium",
            default_model="cloud-smart-o1",
            models=["cloud-smart-o1", "custom-checkpoint"],
        ),
        "code-specialist": ProviderMetadata(
            name="code-specialist",
            capabilities=["code", "general"],
            privacy_status="cloud",
            cost_class="medium",
            latency_class="medium",
            default_model="deepseek-coder",
            models=["deepseek-coder"],
            allow_arbitrary_models=False,
        ),
        "local-ollama": ProviderMetadata(
            name="local-ollama",
            capabilities=["general", "code", "fast", "local"],
            privacy_status="local",
            cost_class="low",
            latency_class="low",
            default_model="llama3-local",
            models=["llama3-local", "qwen-local"],
        ),
        "flexible-provider": ProviderMetadata(
            name="flexible-provider",
            capabilities=["general"],
            privacy_status="cloud",
            default_model="flex-default",
            models=["flex-default"],
            allow_arbitrary_models=True,
        ),
    }


def test_fallback_routing_when_context_is_empty(sample_metadata):
    policy = DeterministicRoutingPolicy()
    sel = policy.select(context=None, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "cloud-standard"
    assert sel.model_name == "cloud-std-v1"
    assert "default" in sel.reason


def test_explicit_override_routing(sample_metadata):
    policy = DeterministicRoutingPolicy()

    # Provider override only
    ctx1 = RoutingContext(explicit_model_override="local-ollama")
    sel1 = policy.select(context=ctx1, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel1.provider_name == "local-ollama"
    assert sel1.model_name == "llama3-local"
    assert sel1.reason == "explicit_provider_override"

    # Provider + Model override (supported model)
    ctx2 = RoutingContext(explicit_model_override="cloud-smart:custom-checkpoint")
    sel2 = policy.select(context=ctx2, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel2.provider_name == "cloud-smart"
    assert sel2.model_name == "custom-checkpoint"
    assert sel2.reason == "explicit_model_override"


def test_explicit_invalid_provider_override_raises_loudly(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(explicit_model_override="nonexistent-provider:some-model")
    with pytest.raises(ValueError, match="is not available"):
        policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")


def test_explicit_unsupported_model_on_known_provider_raises_loudly(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(explicit_model_override="code-specialist:unsupported-gpt-model")
    with pytest.raises(ValueError, match="is not supported by provider 'code-specialist'"):
        policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")


def test_explicit_override_allows_arbitrary_models_when_configured(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(explicit_model_override="flexible-provider:any-experimental-checkpoint")
    sel = policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "flexible-provider"
    assert sel.model_name == "any-experimental-checkpoint"


def test_unsupported_capability_raises_loudly(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(required_capabilities=["quantum_teleportation"])
    with pytest.raises(ValueError, match="No eligible provider found satisfying required capabilities"):
        policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")


def test_privacy_confidential_takes_precedence_over_cost(sample_metadata):
    policy = DeterministicRoutingPolicy()
    # Request confidential + cheap. Even if cloud-standard is cheap, confidential MUST route to local
    ctx = RoutingContext(
        privacy_requirement="confidential",
        cost_preference="low",
    )
    sel = policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "local-ollama"
    assert "confidential_privacy" in sel.reason
    assert "low_cost" in sel.reason


def test_coding_and_low_latency_routing(sample_metadata):
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(
        task_type="coding",
        latency_preference="low",
    )
    # code-specialist has latency medium, local-ollama has code and latency low
    sel = policy.select(context=ctx, available_metadata=sample_metadata, default_provider="cloud-standard")
    assert sel.provider_name == "local-ollama"
    assert "coding" in sel.reason
    assert "low_latency" in sel.reason


def test_reasoning_and_low_cost_routing(sample_metadata):
    # Add a cheap reasoning provider
    meta = dict(sample_metadata)
    meta["budget-reasoner"] = ProviderMetadata(
        name="budget-reasoner",
        capabilities=["reasoning"],
        privacy_status="cloud",
        cost_class="low",
        latency_class="high",
        default_model="budget-r1",
    )
    policy = DeterministicRoutingPolicy()
    ctx = RoutingContext(
        complexity="complex",
        cost_preference="low",
    )
    sel = policy.select(context=ctx, available_metadata=meta, default_provider="cloud-standard")
    assert sel.provider_name == "budget-reasoner"
    assert "reasoning" in sel.reason
    assert "low_cost" in sel.reason


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
    assert "coding" in selection.reason

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


@pytest.mark.asyncio
async def test_routed_model_reaches_openai_outbound_payload(monkeypatch):
    """Verify that the routed model identity strictly reaches the outbound HTTP payload."""
    from app.models.openai_provider import OpenAICompatibleProvider
    captured_payloads = []

    class DummyResponse:
        status_code = 200
        def json(self):
            return {
                "id": "chatcmpl-1",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello world"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        def raise_for_status(self):
            pass

    async def mock_post(self, url, **kwargs):
        captured_payloads.append(kwargs.get("json", {}))
        return DummyResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)

    provider = OpenAICompatibleProvider(api_key="sk-test", base_url="https://api.test/v1", model_name="default-gpt")
    router = ModelRouter()
    router.register_provider(
        provider,
        ProviderMetadata(
            name="openai",
            capabilities=["general", "code"],
            default_model="routed-gpt-4o-mini",
        ),
    )

    # 1. Normal routing by policy
    req1 = ModelRequest(
        messages=[ChatMessage(role=ModelRole.USER, content="Test routing")],
        routing_context=RoutingContext(task_type="coding"),
    )
    await router.route(req1, provider_name="openai")
    assert len(captured_payloads) == 1
    assert captured_payloads[0]["model"] == "routed-gpt-4o-mini"

    # 2. Explicit model override
    req2 = ModelRequest(
        messages=[ChatMessage(role=ModelRole.USER, content="Test override")],
        routing_context=RoutingContext(explicit_model_override="openai:custom-fine-tuned-model"),
    )
    await router.route(req2)
    assert len(captured_payloads) == 2
    assert captured_payloads[1]["model"] == "custom-fine-tuned-model"

