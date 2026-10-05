"""Unit tests for CompositeResearchProvider."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.research.cache import ResearchCache
from app.research.document import FullTextStatus, ParsedDocument, SectionExtractionResult
from app.research.models import ResearchSource, SourceStatus
from app.research.provider import ResearchProviderUnavailable, ResearchSearchUnavailable
from app.research.providers.composite import CompositeResearchProvider
from app.research.tools import ResearchSearchTool


@pytest.fixture
def mock_cache():
    return ResearchCache()


@pytest.mark.asyncio
async def test_composite_provider_deduplication(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    fetcher = MagicMock()

    s2_paper = ResearchSource(
        source_id="s2_abc123",
        canonical_id="arxiv:2401.00001",
        title="Stateful LLM with Persistent Internal State",
        authors=["Alice Scientist"],
        year=2024,
        abstract="S2 abstract text.",
        status=SourceStatus.CANDIDATE,
        metadata={"provider": "semantic_scholar", "arxiv_id": "2401.00001"},
    )
    s2_provider.search = AsyncMock(return_value=[s2_paper])

    arxiv_paper_same = ResearchSource(
        source_id="arxiv_2401_00001",
        canonical_id="arxiv:2401.00001",
        title="Stateful LLM with Persistent Internal State",
        authors=["Alice Scientist", "Bob Coauthor"],
        year=2024,
        abstract="arXiv abstract text.",
        status=SourceStatus.CANDIDATE,
        metadata={
            "provider": "arxiv",
            "arxiv_id": "2401.00001",
            "pdf_url": "https://arxiv.org/pdf/2401.00001.pdf",
            "categories": ["cs.CL"],
        },
    )
    arxiv_provider.fetch_source = AsyncMock(return_value=arxiv_paper_same)
    arxiv_provider.search = AsyncMock(return_value=[arxiv_paper_same])

    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=fetcher,
        cache=mock_cache,
    )

    results = await composite.search("stateful llm", max_results=5)

    # Must be deduplicated down to 1 entry
    assert len(results) == 1
    merged = results[0]
    assert merged.canonical_id == "arxiv:2401.00001"
    assert "semantic_scholar" in merged.metadata.get("providers", [])
    assert "arxiv" in merged.metadata.get("providers", [])
    assert merged.metadata.get("pdf_url") == "https://arxiv.org/pdf/2401.00001.pdf"
    assert merged.authors == ["Alice Scientist", "Bob Coauthor"]


@pytest.mark.asyncio
async def test_composite_provider_s2_failure_fallback_to_arxiv(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    fetcher = MagicMock()

    s2_provider.search = AsyncMock(side_effect=Exception("Semantic Scholar down"))

    arxiv_paper = ResearchSource(
        source_id="arxiv_2402_99999",
        canonical_id="arxiv:2402.99999",
        title="Pure ArXiv Paper",
        status=SourceStatus.CANDIDATE,
        metadata={"provider": "arxiv"},
    )
    arxiv_provider.search = AsyncMock(return_value=[arxiv_paper])

    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=fetcher,
        cache=mock_cache,
    )

    results = await composite.search("test query")
    assert len(results) == 1
    assert results[0].canonical_id == "arxiv:2402.99999"


@pytest.mark.asyncio
async def test_composite_provider_uses_crossref_metadata_as_last_resort(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    crossref_provider = MagicMock()
    s2_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("Semantic Scholar"))
    arxiv_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("arXiv"))
    crossref_source = ResearchSource(
        source_id="crossref_10_5555_aura",
        canonical_id="doi:10.5555/aura",
        title="A Crossref Metadata Result",
        url="https://doi.org/10.5555/aura",
        metadata={"provider": "crossref"},
    )
    crossref_provider.search = AsyncMock(return_value=[crossref_source])
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        crossref_provider=crossref_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    results = await composite.search("metadata result", max_results=3)

    assert [source.canonical_id for source in results] == ["doi:10.5555/aura"]
    crossref_provider.search.assert_awaited_once_with("metadata result", search_type="broad", max_results=3)


@pytest.mark.asyncio
async def test_composite_provider_skips_crossref_when_existing_results_fill_request(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    crossref_provider = MagicMock()
    s2_provider.search = AsyncMock(return_value=[
        ResearchSource(source_id=f"s2_{index}", canonical_id=f"doi:10.5555/{index}", title=f"Paper {index}")
        for index in range(2)
    ])
    arxiv_provider.search = AsyncMock()
    crossref_provider.search = AsyncMock()
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        crossref_provider=crossref_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    await composite.search("enough results", max_results=2)

    crossref_provider.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_composite_provider_falls_back_when_s2_count_is_full_of_duplicates(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    crossref_provider = MagicMock()
    duplicate_sources = [
        ResearchSource(source_id=f"s2_{index}", canonical_id="doi:10.5555/duplicate", title="Same Paper")
        for index in range(2)
    ]
    s2_provider.search = AsyncMock(return_value=duplicate_sources)
    arxiv_provider.search = AsyncMock(return_value=[])
    crossref_source = ResearchSource(
        source_id="crossref_10_5555_unique",
        canonical_id="doi:10.5555/unique",
        title="A Distinct Paper",
        metadata={"provider": "crossref"},
    )
    crossref_provider.search = AsyncMock(return_value=[crossref_source])
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        crossref_provider=crossref_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    results = await composite.search("duplicate query", max_results=2)

    arxiv_provider.search.assert_awaited_once_with("duplicate query", search_type="broad", max_results=2)
    crossref_provider.search.assert_awaited_once_with("duplicate query", search_type="broad", max_results=2)
    assert {source.canonical_id for source in results} == {"doi:10.5555/duplicate", "doi:10.5555/unique"}


@pytest.mark.asyncio
async def test_composite_provider_reports_outage_when_no_source_provider_completed(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    s2_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("Semantic Scholar", "rate limited"))
    arxiv_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("arXiv"))
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    with pytest.raises(ResearchSearchUnavailable) as raised:
        await composite.search("test query")

    assert raised.value.failed_providers == ("Semantic Scholar", "arXiv")


@pytest.mark.asyncio
async def test_composite_provider_keeps_successful_empty_search_distinct_from_outage(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    s2_provider.search = AsyncMock(return_value=[])
    arxiv_provider.search = AsyncMock(return_value=[])
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    assert await composite.search("no matching topic") == []


@pytest.mark.asyncio
async def test_composite_provider_preserves_successful_empty_result_when_arxiv_fails(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    s2_provider.search = AsyncMock(return_value=[])
    arxiv_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("arXiv"))
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    assert await composite.search("no matching topic") == []


@pytest.mark.asyncio
async def test_composite_provider_preserves_successful_empty_arxiv_result_when_s2_fails(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    s2_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("Semantic Scholar"))
    arxiv_provider.search = AsyncMock(return_value=[])
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    assert await composite.search("no matching topic") == []


@pytest.mark.asyncio
async def test_search_tool_does_not_report_provider_outage_as_empty_results(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    s2_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("Semantic Scholar"))
    arxiv_provider.search = AsyncMock(side_effect=ResearchProviderUnavailable("arXiv"))
    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=MagicMock(),
        cache=mock_cache,
    )

    result = await ResearchSearchTool().execute(
        {"query": "test query"}, context={"research_provider": composite}
    )

    assert result.success is False
    assert "could not complete the search" in (result.error or "")
    assert result.metadata["error_code"] == "research_providers_unavailable"
    assert result.metadata["failed_providers"] == ["Semantic Scholar", "arXiv"]


@pytest.mark.asyncio
async def test_composite_provider_fetch_section_fulltext(mock_cache):
    s2_provider = MagicMock()
    arxiv_provider = MagicMock()
    fetcher = MagicMock()

    source = ResearchSource(
        source_id="arxiv_2401_00001",
        canonical_id="arxiv:2401.00001",
        title="Sample Paper",
        status=SourceStatus.INSPECTED,
        sections={"abstract": "Abstract content"},
        metadata={"pdf_url": "https://arxiv.org/pdf/2401.00001.pdf"},
    )
    mock_cache.put_paper(source)

    parsed_doc = ParsedDocument(
        doc_url="https://arxiv.org/pdf/2401.00001.pdf",
        canonical_id="arxiv:2401.00001",
        status=FullTextStatus.AVAILABLE,
        sections={
            "introduction": SectionExtractionResult(
                section_name="introduction",
                content="Introduction text from parsed PDF.",
                start_page=1,
                end_page=2,
            )
        },
    )
    fetcher.fetch_and_parse = AsyncMock(return_value=parsed_doc)

    composite = CompositeResearchProvider(
        s2_provider=s2_provider,
        arxiv_provider=arxiv_provider,
        fetcher=fetcher,
        cache=mock_cache,
    )

    # 1. Fetch existing abstract
    abstract = await composite.fetch_section("arxiv:2401.00001", "abstract")
    assert abstract == "Abstract content"
    fetcher.fetch_and_parse.assert_not_called()

    # 2. Fetch missing introduction -> triggers PDF extraction
    intro = await composite.fetch_section("arxiv:2401.00001", "introduction")
    assert intro == "Introduction text from parsed PDF."
    fetcher.fetch_and_parse.assert_called_once_with(
        "https://arxiv.org/pdf/2401.00001.pdf",
        canonical_id="arxiv:2401.00001",
    )
