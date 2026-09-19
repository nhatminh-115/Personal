"""Unit tests for CompositeResearchProvider."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.research.cache import ResearchCache
from app.research.document import FullTextStatus, ParsedDocument, SectionExtractionResult
from app.research.models import ResearchSource, SourceStatus
from app.research.providers.composite import CompositeResearchProvider


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
