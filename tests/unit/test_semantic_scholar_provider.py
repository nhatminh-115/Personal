"""Unit tests for SemanticScholarResearchProvider."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import pytest

from app.research.cache import ResearchCache
from app.research.document import FullTextStatus
from app.research.provider import ResearchProviderUnavailable
from app.research.providers.semantic_scholar import SemanticScholarResearchProvider


@pytest.fixture
def mock_cache():
    return ResearchCache()


@pytest.mark.asyncio
async def test_semantic_scholar_search_success(mock_cache):
    mock_payload = {
        "data": [
            {
                "paperId": "abcdef1234567890",
                "title": "Stateful Neural Networks with Persistent State",
                "abstract": "We explore architectures with compact persistent internal state.",
                "year": 2024,
                "authors": [{"name": "Alice Researcher"}, {"name": "Bob Scientist"}],
                "venue": "NeurIPS",
                "externalIds": {"ArXiv": "2401.00001", "DOI": "10.1145/123456"},
                "url": "https://www.semanticscholar.org/paper/abcdef1234567890",
                "openAccessPdf": {"url": "https://arxiv.org/pdf/2401.00001.pdf"},
                "publicationDate": "2024-01-15",
                "citationCount": 42,
            }
        ]
    }

    provider = SemanticScholarResearchProvider(api_key="test-api-key", cache=mock_cache)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        results = await provider.search("stateful llm", max_results=5)

        assert len(results) == 1
        source = results[0]
        assert source.title == "Stateful Neural Networks with Persistent State"
        assert source.year == 2024
        assert source.authors == ["Alice Researcher", "Bob Scientist"]
        assert source.abstract == "We explore architectures with compact persistent internal state."
        assert source.metadata["semantic_scholar_id"] == "abcdef1234567890"
        assert source.metadata["arxiv_id"] == "2401.00001"
        assert source.metadata["doi"] == "10.1145/123456"
        assert source.metadata["pdf_url"] == "https://arxiv.org/pdf/2401.00001.pdf"
        assert source.metadata["full_text_status"] == FullTextStatus.AVAILABLE.value
        assert "abstract" in source.sections
        # Verify canonical ID computed using DOI
        assert source.canonical_id == "doi:10.1145/123456"


@pytest.mark.asyncio
async def test_semantic_scholar_missing_abstract(mock_cache):
    mock_payload = {
        "data": [
            {
                "paperId": "noabstract123",
                "title": "Paper Without Abstract",
                "abstract": None,
                "year": 2023,
                "authors": [{"name": "Charlie"}],
                "externalIds": {"ArXiv": "2305.12345"},
            }
        ]
    }

    provider = SemanticScholarResearchProvider(cache=mock_cache)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        results = await provider.search("missing abstract")

        assert len(results) == 1
        assert results[0].abstract is None
        assert "abstract" not in results[0].sections


@pytest.mark.asyncio
async def test_semantic_scholar_rate_limit_and_retry(mock_cache):
    provider = SemanticScholarResearchProvider(cache=mock_cache, max_retries=2)

    resp_429 = MagicMock(spec=httpx.Response)
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "0.1"}

    resp_200 = MagicMock(spec=httpx.Response)
    resp_200.status_code = 200
    resp_200.json.return_value = {"data": [{"paperId": "1", "title": "Success Paper"}]}

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = [resp_429, resp_200]
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            results = await provider.search("retry test")

            assert len(results) == 1
            assert results[0].title == "Success Paper"
            mock_sleep.assert_called_once()
            assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_semantic_scholar_server_error_exhausted(mock_cache):
    provider = SemanticScholarResearchProvider(cache=mock_cache, max_retries=2)

    resp_500 = MagicMock(spec=httpx.Response)
    resp_500.status_code = 500

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = resp_500
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ResearchProviderUnavailable, match="Semantic Scholar"):
                await provider.search("failing server")
            assert mock_get.call_count == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_semantic_scholar_timeout_handling(mock_cache):
    provider = SemanticScholarResearchProvider(cache=mock_cache, max_retries=1)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Connection timed out")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ResearchProviderUnavailable, match="Semantic Scholar"):
                await provider.search("timeout query")


@pytest.mark.asyncio
async def test_semantic_scholar_requests_verify_tls_for_search_and_fetch(mock_cache):
    provider = SemanticScholarResearchProvider(api_key="test-api-key", cache=mock_cache)
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = {}
    clients = []

    def make_client(**kwargs):
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=response)
        clients.append((kwargs, client))
        return client

    with patch("app.research.providers.semantic_scholar.httpx.AsyncClient", side_effect=make_client):
        assert await provider.search("tls verification") == []
        assert await provider.fetch_source("paper-123") is None

    assert len(clients) == 2
    assert all(kwargs.get("verify") is True for kwargs, _ in clients)
    assert all(kwargs.get("follow_redirects") is False for kwargs, _ in clients)


def test_semantic_scholar_headers_with_and_without_api_key():
    p_with_key = SemanticScholarResearchProvider(api_key="secret-key-12345")
    headers = p_with_key._get_headers()
    assert headers["x-api-key"] == "secret-key-12345"
    assert headers["Accept"] == "application/json"

    p_no_key = SemanticScholarResearchProvider(api_key="")
    headers_no_key = p_no_key._get_headers()
    assert "x-api-key" not in headers_no_key
