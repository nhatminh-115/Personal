"""Unit tests for the provider-neutral ModelRouter."""

import pytest
from app.core.errors import ProviderError
from app.models.base import ChatMessage, ModelRequest, ModelResponse, ModelRole, ToolCallRequest
from app.models.mock_provider import MockModelProvider
from app.models.router import ModelRouter


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
