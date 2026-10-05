import logging

import httpx
import pytest

from app.core.errors import ProviderError
from app.models.base import ChatMessage, ModelRequest, ModelRole
from app.models.openai_provider import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_transport_failure_does_not_log_or_raise_raw_diagnostic(monkeypatch, caplog):
    diagnostic = "private runner diagnostic"

    class FailingAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError(
                diagnostic,
                request=httpx.Request("POST", "http://provider.invalid/chat/completions"),
            )

    monkeypatch.setattr("app.models.openai_provider.httpx.AsyncClient", FailingAsyncClient)
    provider = OpenAICompatibleProvider(provider_name="ollama")
    request = ModelRequest(messages=[ChatMessage(role=ModelRole.USER, content="hello")])

    with caplog.at_level(logging.ERROR, logger="aura"):
        with pytest.raises(ProviderError) as error:
            await provider.generate(request)

    assert str(error.value) == "Connection to provider ollama failed."
    assert error.value.__cause__ is None
    assert diagnostic not in caplog.text
