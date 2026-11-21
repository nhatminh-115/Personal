"""Unit tests for dynamic model discovery, provider generalization, and routing policies."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.server import create_app
from app.core.settings import settings
from app.models.base import RoutingContext
from app.models.discovery import (
    ModelCatalogResponse,
    ModelDiscoveryService,
    ProviderEntry,
    infer_tool_support,
    model_discovery_service,
)
from app.models.mock_provider import MockModelProvider
from app.models.openai_provider import OpenAICompatibleProvider
from app.models.router import ModelRouter
from app.models.routing_policy import DeterministicRoutingPolicy, ProviderMetadata


class FakeStreamingResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def aiter_bytes(self, chunk_size=65536):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


@pytest.mark.asyncio
async def test_ollama_discovery_conservative_classification():
    """Ollama discovery strictly classifies tool support using metadata and probes, not name heuristics."""
    svc = ModelDiscoveryService()

    fake_tags = {
        "models": [
            # Model with explicit capability metadata reported by runtime
            {"name": "llama3.2:3b", "model": "llama3.2:3b", "capabilities": ["tools"]},
            # Model without explicit capability metadata -> must be unknown despite "mistral" name
            {"name": "mistral:7b", "model": "mistral:7b"},
            # Model with explicit unsupported metadata
            {"name": "tinyllama:latest", "model": "tinyllama:latest", "tools": False},
        ]
    }

    mock_resp = FakeStreamingResponse(200, fake_tags)

    with patch("httpx.AsyncClient.stream", return_value=mock_resp):
        res = await svc.discover_ollama()

    assert res.id == "ollama"
    assert res.available is True
    assert len(res.models) == 3
    model_map = {m.id: m for m in res.models}
    # Explicit capability -> supported
    assert model_map["llama3.2:3b"].tool_support == "supported"
    # No explicit capability -> unknown (no name-based assumption)
    assert model_map["mistral:7b"].tool_support == "unknown"
    # Explicit false -> unsupported
    assert model_map["tinyllama:latest"].tool_support == "unsupported"


@pytest.mark.asyncio
async def test_lmstudio_discovery_bounds_provider_json(monkeypatch):
    monkeypatch.setattr("app.models.discovery.MAX_PROVIDER_JSON_RESPONSE_BYTES", 8)
    response = FakeStreamingResponse(200, {"data": [{"id": "too-large"}]})

    with patch("httpx.AsyncClient.stream", return_value=response):
        result = await ModelDiscoveryService().discover_lmstudio()

    assert result.available is False
    assert result.models == []


@pytest.mark.asyncio
async def test_lmstudio_discovery_caps_models_exposed(monkeypatch):
    monkeypatch.setattr("app.models.discovery.MAX_DISCOVERED_MODELS", 2)
    response = FakeStreamingResponse(
        200,
        {"data": [{"id": "one"}, {"id": "two"}, {"id": "three"}]},
    )

    with patch("httpx.AsyncClient.stream", return_value=response):
        result = await ModelDiscoveryService().discover_lmstudio()

    assert [model.id for model in result.models] == ["one", "two"]


@pytest.mark.asyncio
async def test_ollama_unavailable():
    """Ollama being offline returns available=False without raising an exception."""
    svc = ModelDiscoveryService()

    with patch("httpx.AsyncClient.stream", side_effect=httpx.ConnectError("Connection refused")):
        res = await svc.discover_ollama()

    assert res.id == "ollama"
    assert res.available is False
    assert len(res.models) == 0


@pytest.mark.asyncio
async def test_lmstudio_discovery_conservative_classification():
    """LM Studio discovery classifies explicitly or defaults to unknown without heuristics."""
    svc = ModelDiscoveryService()

    fake_models = {
        "data": [
            {"id": "qwen2.5-7b-instruct", "object": "model", "capabilities": ["tool_calls"]},
            {"id": "phi-3-mini", "object": "model"},
        ]
    }

    mock_resp = FakeStreamingResponse(200, fake_models)

    with patch("httpx.AsyncClient.stream", return_value=mock_resp):
        res = await svc.discover_lmstudio()

    assert res.id == "lmstudio"
    assert res.available is True
    assert len(res.models) == 2
    model_map = {m.id: m for m in res.models}
    assert model_map["qwen2.5-7b-instruct"].tool_support == "supported"
    assert model_map["phi-3-mini"].tool_support == "unknown"


@pytest.mark.asyncio
async def test_lmstudio_unavailable():
    """LM Studio being offline returns available=False without crashing."""
    svc = ModelDiscoveryService()

    with patch("httpx.AsyncClient.stream", side_effect=httpx.ConnectTimeout("Timed out")):
        res = await svc.discover_lmstudio()

    assert res.id == "lmstudio"
    assert res.available is False
    assert len(res.models) == 0


@pytest.mark.asyncio
async def test_discovery_uses_configured_local_provider_urls(monkeypatch):
    svc = ModelDiscoveryService()
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama-host:11434/v1")
    monkeypatch.setattr(settings, "LMSTUDIO_BASE_URL", "http://studio-host:1234/v1")
    local_provider = ProviderEntry(
        id="ollama", label="Ollama", kind="local", available=False,
        base_url="http://ollama-host:11434/v1",
    )
    ollama = AsyncMock(return_value=local_provider)
    lmstudio = AsyncMock(return_value=local_provider.model_copy(update={"id": "lmstudio", "base_url": "http://studio-host:1234/v1"}))
    with patch.object(svc, "discover_ollama", new=ollama), patch.object(svc, "discover_lmstudio", new=lmstudio):
        await svc.discover_all()
    ollama.assert_awaited_once_with("http://ollama-host:11434/v1")
    lmstudio.assert_awaited_once_with("http://studio-host:1234/v1")


def test_openai_catalog_is_unavailable_without_a_real_configured_value(monkeypatch):
    svc = ModelDiscoveryService()
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "  ")
    entry = svc.get_cloud_openai()
    assert entry.available is False
    assert entry.models == []


def test_openai_compatible_provider_names_do_not_collide():
    """Multiple OpenAICompatibleProvider instances with distinct names co-exist without collision."""
    prov_openai = OpenAICompatibleProvider(provider_name="openai")
    prov_ollama = OpenAICompatibleProvider(provider_name="ollama", base_url="http://127.0.0.1:11434/v1")
    prov_lmstudio = OpenAICompatibleProvider(provider_name="lmstudio", base_url="http://127.0.0.1:1234/v1")

    assert prov_openai.name == "openai"
    assert prov_ollama.name == "ollama"
    assert prov_lmstudio.name == "lmstudio"

    router = ModelRouter()
    router.register_provider(prov_openai)
    router.register_provider(prov_ollama)
    router.register_provider(prov_lmstudio)

    assert router.get_provider("openai").name == "openai"
    assert router.get_provider("ollama").name == "ollama"
    assert router.get_provider("lmstudio").name == "lmstudio"


def test_explicit_routing_and_zero_cloud_fallback():
    """Selecting an explicit local provider routes to it, and errors rather than falling back to cloud."""
    router = ModelRouter()
    policy = DeterministicRoutingPolicy()

    # Register local Ollama
    router.register_provider(
        OpenAICompatibleProvider(provider_name="ollama"),
        ProviderMetadata(
            name="ollama",
            capabilities=["general", "code", "local"],
            privacy_status="local",
            default_model="llama3.2:3b",
            models=["llama3.2:3b"],
            allow_arbitrary_models=True,
            tool_support={"llama3.2:3b": "supported"},
        ),
    )

    # Register cloud OpenAI
    router.register_provider(
        OpenAICompatibleProvider(provider_name="openai"),
        ProviderMetadata(
            name="openai",
            capabilities=["general", "code", "cloud"],
            privacy_status="cloud",
            default_model="gpt-4o",
            models=["gpt-4o"],
        ),
    )

    # 1. Successful local routing
    ctx_local = RoutingContext(explicit_model_override="ollama:llama3.2:3b")
    _, sel_local = router.select_model_for_task(ctx_local)
    assert sel_local.provider_name == "ollama"
    assert sel_local.model_name == "llama3.2:3b"
    assert sel_local.reason == "explicit_model_override"

    from app.core.errors import ModelUnavailable
    # 2. Unavailable local provider must raise error, NOT fall back to OpenAI
    ctx_missing_local = RoutingContext(explicit_model_override="lmstudio:nonexistent")
    with pytest.raises(ModelUnavailable, match="provider 'lmstudio' is not available"):
        router.select_model_for_task(ctx_missing_local)

    # 3. Successful cloud routing
    ctx_cloud = RoutingContext(explicit_model_override="openai:gpt-4o")
    _, sel_cloud = router.select_model_for_task(ctx_cloud)
    assert sel_cloud.provider_name == "openai"
    assert sel_cloud.model_name == "gpt-4o"


def test_unsupported_tool_capability_rejection():
    """If execution requires tools and model is known to be unsupported, raises clean error."""
    router = ModelRouter()
    router.register_provider(
        OpenAICompatibleProvider(provider_name="ollama"),
        ProviderMetadata(
            name="ollama",
            privacy_status="local",
            default_model="chat-only-model",
            models=["chat-only-model"],
            allow_arbitrary_models=True,
            tool_support={"chat-only-model": "unsupported"},
        ),
    )

    ctx = RoutingContext(
        explicit_model_override="ollama:chat-only-model",
        requires_tools=True,
    )

    from app.core.errors import ModelCapabilityMismatch
    with pytest.raises(ModelCapabilityMismatch, match="Selected override model cannot satisfy required agent/tool capability"):
        router.select_model_for_task(ctx)


@pytest.mark.asyncio
async def test_models_api_never_exposes_credentials():
    """GET /v1/models returns catalog with tool support but zero credentials or auth tokens."""
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data

        body_str = resp.text.lower()
        # Verify no secret keywords leaked
        assert "api_key" not in body_str
        assert "authorization" not in body_str
        assert "bearer" not in body_str
        assert "dummy-key" not in body_str

        # Check provider structure
        for prov in data["providers"]:
            assert "id" in prov
            assert "label" in prov
            assert "kind" in prov
            assert "available" in prov
            assert "models" in prov
            for m in prov["models"]:
                assert "id" in m
                assert "tool_support" in m
                assert m["tool_support"] in {"supported", "unsupported", "unknown"}
                assert m.get("reasoning_support", "unknown") in {"instant", "low", "medium", "high", "max", "fixed_by_model", "unsupported", "unknown"}
                assert "vision_support" in m and "structured_output_support" in m


@pytest.mark.asyncio
async def test_models_api_redacts_credentials_embedded_in_provider_base_urls(monkeypatch):
    configured_url = (
        "https://aura-user:private-password@model-host.internal/v1"
        "?api_key=query-secret&region=us&access_token=access-secret"
        "&X-Amz-Signature=sig-secret#private-fragment"
    )
    catalog = ModelCatalogResponse(providers=[ProviderEntry(
        id="ollama",
        label="Ollama",
        kind="local",
        available=False,
        base_url=configured_url,
        privacy_status="local",
    )])
    monkeypatch.setattr(
        "app.api.routes.models.model_discovery_service.discover_all",
        AsyncMock(return_value=catalog),
    )
    monkeypatch.setattr(
        "app.api.routes.models.model_discovery_service.register_discovered_providers",
        AsyncMock(return_value=catalog),
    )

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/models")

    assert response.status_code == 200
    data = response.json()
    assert data["providers"][0]["base_url"] == (
        "https://model-host.internal/v1"
        "?api_key=%5BREDACTED%5D&region=us&access_token=%5BREDACTED%5D"
        "&X-Amz-Signature=%5BREDACTED%5D"
    )
    for secret in ("aura-user", "private-password", "query-secret", "access-secret", "sig-secret", "private-fragment"):
        assert secret not in response.text


@pytest.mark.asyncio
async def test_capability_probe_endpoint(monkeypatch):
    app = create_app()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cloud = await client.post(
            "/v1/models/probe",
            json={"provider_id": "openai", "model_id": "gpt-4o"},
        )
        assert cloud.status_code == 200
        assert cloud.json()["tool_support"] == "supported"

        private_diagnostic = "private runtime body token=probe-secret"

        class FakeProviderClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            def stream(self, *_args, **_kwargs):
                return FakeStreamingResponse(400, {"error": {"message": private_diagnostic}})

        monkeypatch.setattr("app.models.discovery.httpx.AsyncClient", FakeProviderClient)
        rejected = await client.post(
            "/v1/models/probe",
            json={"provider_id": "ollama", "model_id": "test-model"},
        )

        assert rejected.status_code == 200
        assert rejected.json()["tool_support"] == "unknown"
        assert private_diagnostic not in rejected.text


@pytest.mark.asyncio
async def test_probe_oversized_response_remains_unknown(monkeypatch):
    monkeypatch.setattr("app.models.discovery.MAX_CAPABILITY_PROBE_RESPONSE_BYTES", 8)
    response = FakeStreamingResponse(
        200,
        {"choices": [{"message": {"tool_calls": [{"id": "call"}]}}]},
    )

    with patch("httpx.AsyncClient.stream", return_value=response):
        result = await ModelDiscoveryService().probe_model_capability("ollama", "test-model")

    assert result.tool_support == "unknown"
    assert "oversized" in result.details.lower()


@pytest.mark.asyncio
async def test_probe_connection_failure_yields_unknown_not_unsupported():
    svc = ModelDiscoveryService()
    private_diagnostic = "https://local.example/models?token=probe-secret"

    with patch(
        "httpx.AsyncClient.stream",
        side_effect=httpx.ConnectTimeout(f"Connection timed out: {private_diagnostic}"),
    ):
        res = await svc.probe_model_capability("ollama", "test-model")

    assert res.tool_support == "unknown"
    assert "timed out" in res.details.lower() or "connection" in res.details.lower()
    assert private_diagnostic not in res.details
    assert svc._probed_cache.get("ollama:test-model") == "unknown"


@pytest.mark.asyncio
async def test_probe_http_400_is_ambiguous_and_does_not_expose_provider_body():
    svc = ModelDiscoveryService()
    private_diagnostic = "private runtime body token=probe-secret"
    fake_resp = FakeStreamingResponse(400, {"error": {"message": private_diagnostic}})

    with patch("httpx.AsyncClient.stream", return_value=fake_resp):
        result = await svc.probe_model_capability("ollama", "test-model")

    assert result.tool_support == "unknown"
    assert "unknown" in result.details.lower()
    assert private_diagnostic not in result.details
    assert svc._probed_cache.get("ollama:test-model") == "unknown"


@pytest.mark.asyncio
async def test_unexpected_probe_failure_does_not_expose_exception_text():
    svc = ModelDiscoveryService()
    private_diagnostic = "unexpected private provider diagnostic"

    with patch("httpx.AsyncClient.stream", side_effect=RuntimeError(private_diagnostic)):
        result = await svc.probe_model_capability("ollama", "test-model")

    assert result.tool_support == "unknown"
    assert "failed unexpectedly" in result.details.lower()
    assert private_diagnostic not in result.details


@pytest.mark.asyncio
async def test_probe_success_without_tool_calls_remains_unknown():
    svc = ModelDiscoveryService()
    fake_resp = FakeStreamingResponse(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I cannot call functions.",
                    }
                }
            ]
        },
    )

    with patch("httpx.AsyncClient.stream", return_value=fake_resp):
        res = await svc.probe_model_capability("ollama", "chat-only-model")

    assert res.tool_support == "unknown"
    assert "without a tool call" in res.details.lower()
    assert svc._probed_cache.get("ollama:chat-only-model") == "unknown"


@pytest.mark.asyncio
async def test_probe_success_with_tool_calls_yields_supported():
    svc = ModelDiscoveryService()
    fake_resp = FakeStreamingResponse(
        200,
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "probe_test", "arguments": '{"status":"ok"}'},
                            }
                        ],
                    }
                }
            ]
        },
    )

    with patch("httpx.AsyncClient.stream", return_value=fake_resp):
        res = await svc.probe_model_capability("ollama", "tool-capable-model")

    assert res.tool_support == "supported"
    assert svc._probed_cache.get("ollama:tool-capable-model") == "supported"


@pytest.mark.asyncio
async def test_no_redundant_discovery_on_get_and_refresh():
    """GET /v1/models and POST /v1/models/refresh execute exactly one discovery snapshot per call."""
    app = create_app()
    transport = ASGITransport(app=app)

    with patch("app.models.discovery.model_discovery_service.discover_all", wraps=model_discovery_service.discover_all) as mock_discover:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. GET /v1/models
            resp1 = await client.get("/v1/models")
            assert resp1.status_code == 200
            assert mock_discover.call_count == 1

            # 2. POST /v1/models/refresh
            mock_discover.reset_mock()
            resp2 = await client.post("/v1/models/refresh")
            assert resp2.status_code == 200
            assert mock_discover.call_count == 1
