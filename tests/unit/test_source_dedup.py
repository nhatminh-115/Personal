"""Unit tests for canonical source deduplication and identifier extraction."""

import pytest
from app.research.dedup import (
    SourceDeduplicator,
    compute_canonical_id,
    extract_arxiv_id,
    extract_doi,
    normalize_title,
)
from app.research.models import ResearchSource, SourceStatus


def test_normalize_title():
    raw1 = "Stateful Multi-Turn Agent Workflows: A Graph Approach!"
    raw2 = "  stateful   multi-turn   agent  workflows a graph approach  "
    assert normalize_title(raw1) == normalize_title(raw2)
    assert normalize_title(raw1) == "stateful multi turn agent workflows a graph approach"


def test_extract_arxiv_id():
    assert extract_arxiv_id("arXiv:2308.1001v2 [cs.AI]") == "2308.1001"
    assert extract_arxiv_id("https://arxiv.org/abs/2401.5502") == "2401.5502"
    assert extract_arxiv_id("cs.AI/0102003") == "cs.ai/0102003"
    assert extract_arxiv_id("Regular title without arxiv") is None


def test_extract_doi():
    assert extract_doi("https://doi.org/10.1145/3372297.3417878") == "10.1145/3372297.3417878"
    assert extract_doi("doi:10.1016/j.artint.2020.103348;") == "10.1016/j.artint.2020.103348"
    assert extract_doi("No doi in text") is None


def test_compute_canonical_id_precedence():
    # 1. DOI takes precedence
    id1 = compute_canonical_id(
        title="Some Paper",
        url="https://arxiv.org/abs/2308.1001",
        metadata={"doi": "10.1145/12345.67890"},
    )
    assert id1 == "doi:10.1145/12345.67890"

    # 2. arXiv ID if no DOI
    id2 = compute_canonical_id(
        title="Some Paper",
        url="https://arxiv.org/abs/2308.1001",
        metadata={},
    )
    assert id2 == "arxiv:2308.1001"

    # 3. Canonical URL
    id3 = compute_canonical_id(
        title="OpenReview Paper",
        url="https://openreview.net/forum?id=abc123xyz",
        metadata={},
    )
    assert id3 == "url:https://openreview.net/forum"

    # 4. Title hash fallback
    id4 = compute_canonical_id(
        title="Unique Architecture Benchmark",
        url="https://company.internal/doc",
        metadata={},
    )
    assert id4.startswith("title:")


def test_source_deduplicator_merges_duplicate_sources():
    # Source A from arXiv
    src_a = ResearchSource(
        source_id="src_arxiv",
        canonical_id="arxiv:2308.1001",
        title="Stateful Multi-Turn Agent Workflows",
        authors=["Alice Chen"],
        year=2023,
        url="https://arxiv.org/abs/2308.1001",
        abstract="Short abstract",
        sections={"introduction": "Intro content from arXiv"},
        status=SourceStatus.CANDIDATE,
        relevance_score=0.9,
    )

    # Source B from Semantic Scholar / Mirror for the same paper
    src_b = ResearchSource(
        source_id="src_mirror",
        canonical_id="arxiv:2308.1001",
        title="Stateful Multi-Turn Agent Workflows: A Comprehensive Graph Approach",
        authors=["Alice Chen", "Bob Davis"],
        year=2023,
        url="https://semanticscholar.org/paper/12345",
        abstract="Much longer abstract with full technical details.",
        sections={
            "methods": "Detailed methods content.",
            "limitations": "Limitations content.",
        },
        status=SourceStatus.CANDIDATE,
        relevance_score=0.95,
    )

    existing: dict[str, ResearchSource] = {src_a.source_id: src_a}
    distinct_new = SourceDeduplicator.deduplicate([src_b], existing_sources=existing)

    # Duplicate should be merged into existing, not added as a new source
    assert len(distinct_new) == 0
    merged = existing[src_a.source_id]

    # Check that metadata merged properly
    assert "https://semanticscholar.org/paper/12345" in merged.aliases
    assert "methods" in merged.sections
    assert "introduction" in merged.sections
    assert "limitations" in merged.sections
    assert "Much longer abstract" in merged.abstract
    assert "Bob Davis" in merged.authors


def test_source_deduplicator_keeps_distinct_sources():
    src_1 = ResearchSource(
        source_id="s1",
        canonical_id="arxiv:2308.1001",
        title="Stateful Agents",
    )
    src_2 = ResearchSource(
        source_id="s2",
        canonical_id="arxiv:2401.5502",
        title="Pipeline Checkpointing",
    )

    existing = {src_1.source_id: src_1}
    distinct_new = SourceDeduplicator.deduplicate([src_2], existing_sources=existing)

    assert len(distinct_new) == 1
    assert distinct_new[0].source_id == "s2"
