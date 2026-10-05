"""Unit tests for the metadata-only Crossref research provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.research.cache import ResearchCache
from app.research.provider import ResearchProviderUnavailable
from app.research.providers.crossref import CrossrefResearchProvider


@pytest.mark.asyncio
async def test_crossref_search_maps_only_bibliographic_metadata():
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "message": {
            "items": [
                {
                    "DOI": "10.5555/Example.1",
                    "title": ["A metadata-only result"],
                    "author": [{"given": "Ada", "family": "Lovelace"}],
                    "published-print": {"date-parts": [[2024, 2, 3]]},
                    "container-title": ["Journal of Tests"],
                    "publisher": "Example Press",
                    "type": "journal-article",
                    "abstract": "Must not be requested or exposed.",
                }
            ]
        }
    }
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    cache = ResearchCache()
    provider = CrossrefResearchProvider(cache=cache)

    with patch("app.research.providers.crossref.httpx.AsyncClient", return_value=client_context) as factory:
        results = await provider.search("metadata-only result", max_results=2)

    assert factory.call_args.kwargs["follow_redirects"] is False
    request_params = client.get.call_args.kwargs["params"]
    assert request_params["query.bibliographic"] == "metadata-only result"
    assert "abstract" not in request_params["select"]
    assert "abstract" not in results[0].sections
    assert results[0].canonical_id == "doi:10.5555/example.1"
    assert results[0].authors == ["Ada Lovelace"]
    assert results[0].year == 2024
    assert results[0].venue == "Journal of Tests"
    assert results[0].metadata["provider"] == "crossref"
    assert cache.get_paper("doi:10.5555/example.1") is not None


@pytest.mark.asyncio
async def test_crossref_empty_search_is_successful_empty_result():
    response = MagicMock(status_code=200)
    response.json.return_value = {"message": {"items": []}}
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    provider = CrossrefResearchProvider(cache=ResearchCache())

    with patch("app.research.providers.crossref.httpx.AsyncClient", return_value=client_context):
        assert await provider.search("no matching work") == []


@pytest.mark.asyncio
async def test_crossref_http_error_is_reported_without_query_text():
    response = MagicMock(status_code=503)
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    provider = CrossrefResearchProvider(cache=ResearchCache(), max_retries=1)

    with patch("app.research.providers.crossref.httpx.AsyncClient", return_value=client_context):
        with patch("app.research.providers.crossref.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ResearchProviderUnavailable, match="Crossref is temporarily unavailable") as raised:
                await provider.search("private research query", max_results=1)
    assert "private research query" not in str(raised.value)


@pytest.mark.asyncio
async def test_crossref_transport_diagnostic_is_not_returned_or_chained():
    diagnostic = "private Crossref transport diagnostic"
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError(diagnostic))
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    provider = CrossrefResearchProvider(cache=ResearchCache(), max_retries=1)

    with patch("app.research.providers.crossref.httpx.AsyncClient", return_value=client_context):
        with patch("app.research.providers.crossref.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ResearchProviderUnavailable, match="Crossref is temporarily unavailable") as raised:
                await provider.search("query", max_results=1)

    assert diagnostic not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.asyncio
async def test_crossref_rate_limit_retries_with_bounded_retry_after():
    rate_limited = MagicMock(status_code=429, headers={"Retry-After": "120"})
    recovered = MagicMock(status_code=200)
    recovered.json.return_value = {"message": {"items": []}}
    client = MagicMock()
    client.get = AsyncMock(side_effect=[rate_limited, recovered])
    client_context = MagicMock()
    client_context.__aenter__ = AsyncMock(return_value=client)
    client_context.__aexit__ = AsyncMock(return_value=False)
    provider = CrossrefResearchProvider(cache=ResearchCache(), max_retries=1)

    with patch("app.research.providers.crossref.httpx.AsyncClient", return_value=client_context):
        with patch("app.research.providers.crossref.asyncio.sleep", new_callable=AsyncMock) as sleep:
            assert await provider.search("public test query") == []

    assert client.get.await_count == 2
    sleep.assert_awaited_once_with(15.0)


@pytest.mark.asyncio
async def test_crossref_fetch_section_never_returns_full_text():
    provider = CrossrefResearchProvider(cache=ResearchCache())

    assert await provider.fetch_section("doi:10.5555/example", "abstract") is None
