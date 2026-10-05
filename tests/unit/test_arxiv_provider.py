"""Unit tests for ArxivResearchProvider and ArxivRateLimiter."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import pytest

from app.research.cache import ResearchCache
from app.research.document import FullTextStatus, ParsedDocument, SectionExtractionResult
from app.research.provider import ResearchProviderUnavailable
from app.research.providers.arxiv import ArxivRateLimiter, ArxivResearchProvider


SAMPLE_ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2312.00752v1</id>
    <published>2023-12-01T18:00:00Z</published>
    <title> Mamba: Linear-Time Sequence Modeling with Selective State Spaces </title>
    <summary> Foundation models now power most applications in deep learning.
    We introduce Mamba with selective state spaces. </summary>
    <author>
      <name>Albert Gu</name>
    </author>
    <author>
      <name>Tri Dao</name>
    </author>
    <link href="http://arxiv.org/abs/2312.00752v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2312.00752v1" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="cs.AI"/>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_arxiv_rate_limiter():
    current_time = 100.0

    def fake_time():
        return current_time

    slept = []

    async def fake_sleep(duration):
        nonlocal current_time
        slept.append(duration)
        current_time += duration

    limiter = ArxivRateLimiter(min_interval_seconds=3.0, time_func=fake_time, sleep_func=fake_sleep)

    # First acquire: no sleep needed
    await limiter.acquire()
    assert len(slept) == 0

    # Advance clock by 1.0s (less than 3.0s interval)
    current_time += 1.0

    # Second acquire: must sleep 2.0s
    await limiter.acquire()
    assert len(slept) == 1
    assert pytest.approx(slept[0], 0.01) == 2.0


@pytest.mark.asyncio
async def test_arxiv_search_and_xml_parsing():
    cache = ResearchCache()
    limiter = ArxivRateLimiter(min_interval_seconds=0.0)
    provider = ArxivResearchProvider(rate_limiter=limiter, cache=cache)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_ARXIV_XML

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp

        results = await provider.search("mamba linear-time", max_results=5)

        assert len(results) == 1
        source = results[0]
        assert source.canonical_id == "arxiv:2312.00752"
        assert source.source_id == "arxiv_2312_00752"
        assert source.title == "Mamba: Linear-Time Sequence Modeling with Selective State Spaces"
        assert source.authors == ["Albert Gu", "Tri Dao"]
        assert source.year == 2023
        assert "Foundation models" in source.abstract
        assert source.metadata["pdf_url"] == "http://arxiv.org/pdf/2312.00752v1"
        assert source.metadata["full_text_status"] == FullTextStatus.AVAILABLE.value
        assert "abstract" in source.sections


@pytest.mark.asyncio
async def test_arxiv_search_invalid_xml():
    cache = ResearchCache()
    limiter = ArxivRateLimiter(min_interval_seconds=0.0)
    provider = ArxivResearchProvider(rate_limiter=limiter, cache=cache)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = "<not-valid-xml"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with pytest.raises(ResearchProviderUnavailable, match="unreadable search response"):
            await provider.search("error query")


@pytest.mark.asyncio
async def test_arxiv_search_valid_empty_feed_returns_no_results():
    provider = ArxivResearchProvider(rate_limiter=ArxivRateLimiter(min_interval_seconds=0.0), cache=ResearchCache())
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        assert await provider.search("valid no matches") == []


@pytest.mark.asyncio
async def test_arxiv_search_empty_success_body_is_provider_unavailable():
    provider = ArxivResearchProvider(rate_limiter=ArxivRateLimiter(min_interval_seconds=0.0), cache=ResearchCache())
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = ""

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(ResearchProviderUnavailable, match="empty search response"):
            await provider.search("empty successful response")


@pytest.mark.asyncio
async def test_arxiv_search_wrong_xml_root_is_provider_unavailable():
    provider = ArxivResearchProvider(rate_limiter=ArxivRateLimiter(min_interval_seconds=0.0), cache=ResearchCache())
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = "<html></html>"

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        with pytest.raises(ResearchProviderUnavailable, match="invalid search response"):
            await provider.search("wrong XML root")


@pytest.mark.asyncio
async def test_arxiv_api_client_does_not_follow_redirects():
    provider = ArxivResearchProvider(rate_limiter=ArxivRateLimiter(min_interval_seconds=0.0))
    response = MagicMock(spec=httpx.Response)
    response.status_code = 302
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.research.providers.arxiv.httpx.AsyncClient", return_value=client) as client_factory:
        assert await provider._execute_arxiv_request({"search_query": "all:test"}) is None

    assert client_factory.call_args.kwargs["follow_redirects"] is False


@pytest.mark.asyncio
async def test_arxiv_transport_diagnostic_is_not_logged_or_returned(caplog):
    provider = ArxivResearchProvider(rate_limiter=ArxivRateLimiter(min_interval_seconds=0.0))
    diagnostic = "private upstream diagnostic"
    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError(diagnostic))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.research.providers.arxiv.httpx.AsyncClient", return_value=client):
        with patch("app.research.providers.arxiv.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ResearchProviderUnavailable, match="arXiv") as error:
                await provider.search("persistent context")

    assert client.get.await_count == 3
    assert diagnostic not in caplog.text
    assert diagnostic not in str(error.value)


@pytest.mark.asyncio
async def test_arxiv_rate_limit_respects_bounded_retry_after_delay():
    provider = ArxivResearchProvider(rate_limiter=ArxivRateLimiter(min_interval_seconds=0.0))
    rate_limited = MagicMock(spec=httpx.Response)
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0.25"}
    success = MagicMock(spec=httpx.Response)
    success.status_code = 200
    success.text = '<feed xmlns="http://www.w3.org/2005/Atom" />'
    client = MagicMock()
    client.get = AsyncMock(side_effect=[rate_limited, success])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.research.providers.arxiv.httpx.AsyncClient", return_value=client):
        with patch("app.research.providers.arxiv.asyncio.sleep", new_callable=AsyncMock) as sleep:
            response = await provider._execute_arxiv_request({"search_query": "all:test"})

    assert response == '<feed xmlns="http://www.w3.org/2005/Atom" />'
    sleep.assert_awaited_once_with(0.25)


@pytest.mark.asyncio
async def test_arxiv_fetch_section_with_pdf_extraction(tmp_path):
    cache = ResearchCache(cache_dir=tmp_path)
    limiter = ArxivRateLimiter(min_interval_seconds=0.0)
    provider = ArxivResearchProvider(rate_limiter=limiter, cache=cache)

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_ARXIV_XML

    parsed_doc = ParsedDocument(
        doc_url="http://arxiv.org/pdf/2312.00752v1",
        canonical_id="arxiv:2312.00752",
        status=FullTextStatus.AVAILABLE,
        total_pages=10,
        sections={
            "method": SectionExtractionResult(
                section_name="method",
                content="We introduce a data-dependent selection mechanism for state space models.",
                start_page=3,
                end_page=5,
            )
        },
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with patch(
            "app.research.document.document_fetcher.fetch_and_parse",
            new_callable=AsyncMock,
        ) as mock_fetch_doc:
            mock_fetch_doc.return_value = parsed_doc

            # Fetch existing abstract
            abstract = await provider.fetch_section("arxiv:2312.00752", "abstract")
            assert abstract is not None
            assert "Foundation models" in abstract

            # Fetch method (triggers PDF fetch)
            method_text = await provider.fetch_section("arxiv:2312.00752", "method")
            assert method_text is not None
            assert "data-dependent selection mechanism" in method_text
            mock_fetch_doc.assert_called_once()
