"""Unit tests for ArxivResearchProvider and ArxivRateLimiter."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
import pytest

from app.research.cache import ResearchCache
from app.research.document import FullTextStatus, ParsedDocument, SectionExtractionResult
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
        results = await provider.search("error query")
        assert results == []


@pytest.mark.asyncio
async def test_arxiv_fetch_section_with_pdf_extraction():
    cache = ResearchCache()
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
