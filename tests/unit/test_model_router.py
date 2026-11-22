"""Unit tests for the provider-neutral ModelRouter."""

import pytest
from app.core.errors import PrivacyBoundaryViolation, ProviderError
from app.models.base import ChatMessage, ModelRequest, ModelResponse, ModelRole, RoutingContext, ToolCallRequest
from app.models.mock_provider import MockModelProvider
from app.models.router import ModelRouter
from app.models.routing_policy import ProviderMetadata


@pytest.mark.asyncio
async def test_mock_provider_deterministic_response():
    provider = MockModelProvider(default_response="Deterministic Hello")
    request = ModelRequest(messages=[ChatMessage(role=ModelRole.USER, content="ping")])
    response = await provider.generate(request)

    assert response.content is not None
    assert "Processed 'ping'" in response.content
    assert len(provider.call_history) == 1


@pytest.mark.asyncio
async def test_mock_provider_queue_response():
    provider = MockModelProvider()
    custom_resp = ModelResponse(
        content="Custom Queued Answer",
        tool_calls=[ToolCallRequest(id="123", name="test_tool", arguments={})],
    )
    provider.queue_response(custom_resp)

    request = ModelRequest(messages=[ChatMessage(role=ModelRole.USER, content="anything")])
    response = await provider.generate(request)

    assert response.content == "Custom Queued Answer"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "test_tool"


@pytest.mark.asyncio
async def test_router_retrieves_registered_provider():
    router = ModelRouter(default_provider_name="mock")
    provider = router.get_provider("mock")
    assert provider.name == "mock"


@pytest.mark.asyncio
async def test_router_unregistered_provider_raises_error():
    router = ModelRouter(default_provider_name="mock")
    with pytest.raises(ProviderError) as exc_info:
        router.get_provider("non_existent_provider")
    assert "not registered" in str(exc_info.value)


def test_unconfigured_default_fails_clearly_without_selecting_mock():
    router = ModelRouter(default_provider_name="unconfigured")

    with pytest.raises(ProviderError, match="No model provider is configured"):
        router.select_model_for_task(RoutingContext())


def test_explicit_model_route_remains_available_with_unconfigured_default():
    router = ModelRouter(default_provider_name="unconfigured")

    provider, selection = router.select_model_for_task(
        RoutingContext(explicit_model_override="mock:mock-default")
    )

    assert provider.name == "mock"
    assert selection.model_name == "mock-default"


@pytest.mark.asyncio
@pytest.mark.parametrize("privacy", ["confidential", "local_only"])
async def test_explicit_provider_route_blocks_cloud_before_provider_call(privacy):
    cloud_provider = MockModelProvider()
    router = ModelRouter(default_provider_name="mock")
    router.register_provider(
        cloud_provider,
        ProviderMetadata(
            name="mock",
            privacy_status="cloud",
            default_model="mock-default",
        ),
    )
    request = ModelRequest(
        messages=[ChatMessage(role=ModelRole.USER, content="private request")],
        routing_context=RoutingContext(privacy_requirement=privacy),
    )

    with pytest.raises(PrivacyBoundaryViolation):
        await router.route(request, provider_name="mock")

    assert cloud_provider.call_history == []
