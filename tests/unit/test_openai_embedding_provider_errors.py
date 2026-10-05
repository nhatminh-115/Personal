from types import SimpleNamespace

import httpx
import pytest

from app.memory.embeddings.base import EmbeddingRequest
from app.memory.embeddings.openai_provider import EmbeddingProviderError, OpenAIEmbeddingProvider


@pytest.mark.asyncio
async def test_http_error_does_not_expose_provider_response_body(monkeypatch):
    diagnostic = "private embedding response diagnostic"

    class ErrorResponseClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=503, text=diagnostic)

    monkeypatch.setattr("app.memory.embeddings.openai_provider.httpx.AsyncClient", ErrorResponseClient)
    provider = OpenAIEmbeddingProvider(api_key="test-key")

    with pytest.raises(EmbeddingProviderError, match="returned HTTP 503") as error:
        await provider.embed(EmbeddingRequest(texts=["private user text"]))

    assert diagnostic not in str(error.value)
    assert "private user text" not in str(error.value)


@pytest.mark.asyncio
async def test_transport_error_does_not_expose_raw_diagnostic(monkeypatch):
    diagnostic = "private transport diagnostic"

    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError(
                diagnostic,
                request=httpx.Request("POST", "https://api.example.test/embeddings"),
            )

    monkeypatch.setattr("app.memory.embeddings.openai_provider.httpx.AsyncClient", FailingClient)
    provider = OpenAIEmbeddingProvider(api_key="test-key")

    with pytest.raises(EmbeddingProviderError, match="Network failure connecting") as error:
        await provider.embed(EmbeddingRequest(texts=["private user text"]))

    assert diagnostic not in str(error.value)
    assert "private user text" not in str(error.value)
    assert error.value.__cause__ is None
