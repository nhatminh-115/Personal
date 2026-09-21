"""Unit tests for dynamic model discovery, provider generalization, and routing policies."""

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.server import create_app
from app.core.settings import settings
from app.models.base import RoutingContext
from app.models.discovery import (
    ModelDiscoveryService,
    infer_tool_support,
    model_discovery_service,
)
from app.models.mock_provider import MockModelProvider
from app.models.openai_provider import OpenAICompatibleProvider
from app.models.router import ModelRouter
from app.models.routing_policy import DeterministicRoutingPolicy, ProviderMetadata


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

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_tags

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
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
async def test_ollama_unavailable():
    """Ollama being offline returns available=False without raising an exception."""
    svc = ModelDiscoveryService()

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
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

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_models

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
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

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectTimeout("Timed out")):
        res = await svc.discover_lmstudio()

    assert res.id == "lmstudio"
    assert res.available is False
    assert len(res.models) == 0


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


@pytest.mark.asyncio
async def test_capability_probe_endpoint():
    """POST /v1/models/probe tests tool-calling behavior."""
    app = create_app()
    transport = ASGITransport(app=app)

    # Cloud/Mock providers return supported by default
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/models/probe",
            json={"provider_id": "openai", "model_id": "gpt-4o"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_support"] == "supported"


@pytest.mark.asyncio
async def test_probe_connection_failure_yields_unknown_not_unsupported():
    """Failed connection or timeout during probe must yield 'unknown' / provider unavailable, NOT 'unsupported'."""
    svc = ModelDiscoveryService()

    with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectTimeout("Connection timed out")):
        res = await svc.probe_model_capability("ollama", "test-model")

    assert res.tool_support == "unknown"
    assert "timed out" in res.details.lower() or "connection" in res.details.lower()
    # Cache must reflect unknown, not unsupported
    assert svc._probed_cache.get("ollama:test-model") == "unknown"


@pytest.mark.asyncio
async def test_probe_success_without_tool_calls_yields_unsupported():
    """When runtime responds 200 but model emits no tool calls, it provides meaningful evidence of 'unsupported'."""
    svc = ModelDiscoveryService()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "I cannot call functions.",
                }
            }
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fake_resp):
        res = await svc.probe_model_capability("ollama", "chat-only-model")

    assert res.tool_support == "unsupported"
    assert "without tool calls" in res.details.lower()
    assert svc._probed_cache.get("ollama:chat-only-model") == "unsupported"


@pytest.mark.asyncio
async def test_probe_success_with_tool_calls_yields_supported():
    """When runtime responds 200 and model emits tool calls, marks 'supported'."""
    svc = ModelDiscoveryService()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
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
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fake_resp):
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

