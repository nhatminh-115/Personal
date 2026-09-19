"""Unit tests for Research domain models, serialization, and typing."""

import pytest
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchGoal,
    ResearchQuery,
    ResearchResult,
    ResearchSource,
    ResearchState,
    ResearchStatus,
    SourceStatus,
)


def test_research_goal_creation_and_defaults():
    goal = ResearchGoal(
        goal_id="goal_123",
        user_query="Find prior art on stateful LLM execution",
        project_name="Atlas",
        research_questions=["How does Paper A manage state?", "Does Paper B support checkpoints?"],
    )
    assert goal.goal_id == "goal_123"
    assert goal.project_name == "Atlas"
    assert len(goal.research_questions) == 2
    assert goal.created_at > 0


def test_research_source_sections_and_canonical_id():
    src = ResearchSource(
        source_id="src_1",
        canonical_id="arxiv:2308.1001",
        title="Stateful Multi-Turn Agent Workflows",
        authors=["Alice Chen", "Bob Davis"],
        year=2023,
        url="https://arxiv.org/abs/2308.1001",
        abstract="A paper on agent state.",
        sections={
            "abstract": "A paper on agent state.",
            "methods": "We use in-memory graphs.",
            "limitations": "Ephemeral only.",
        },
        status=SourceStatus.SELECTED,
        relevance_score=0.9,
    )
    assert src.canonical_id == "arxiv:2308.1001"
    assert src.sections["methods"] == "We use in-memory graphs."
    assert src.status == SourceStatus.SELECTED

    # Serialization roundtrip
    dumped = src.model_dump()
    loaded = ResearchSource.model_validate(dumped)
    assert loaded.source_id == src.source_id
    assert loaded.sections == src.sections


def test_evidence_item_creation():
    ev = EvidenceItem(
        evidence_id="ev_001",
        source_id="src_1",
        source_title="Stateful Multi-Turn Agent Workflows",
        source_locator="Section 3: Methods",
        extracted_text="State is stored in memory and lost upon crash.",
        summary="Indicates ephemeral memory without checkpointing",
        confidence=0.95,
    )
    assert ev.evidence_id == "ev_001"
    assert ev.confidence == 0.95
    assert "Section 3" in ev.source_locator


def test_research_claim_types():
    # Fact requires evidence
    fact_claim = ResearchClaim(
        claim_id="cl_01",
        claim_text="Paper 1 uses in-memory graphs without persistence.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )
    assert fact_claim.claim_type == ClaimType.SOURCE_SUPPORTED_FACT
    assert "ev_001" in fact_claim.evidence_ids

    # Inference can stand with rationale
    inf_claim = ResearchClaim(
        claim_id="cl_02",
        claim_text="Paper 1 is unsuitable for mission-critical enterprise workflows due to crash vulnerability.",
        claim_type=ClaimType.SPECIALIST_INFERENCE,
        evidence_ids=["ev_001"],
    )
    assert inf_claim.claim_type == ClaimType.SPECIALIST_INFERENCE

    # Hypothesis
    hypo_claim = ResearchClaim(
        claim_id="cl_03",
        claim_text="Combining Paper 1's graph with SQLite WAL checkpoints could provide fault tolerance.",
        claim_type=ClaimType.HYPOTHESIS,
    )
    assert hypo_claim.claim_type == ClaimType.HYPOTHESIS
    assert hypo_claim.evidence_ids == []


def test_research_result_aggregation():
    goal = ResearchGoal(goal_id="g1", user_query="Evaluate novelty")
    src = ResearchSource(source_id="s1", canonical_id="arxiv:2308.1001", title="Title A")
    ev = EvidenceItem(
        evidence_id="e1",
        source_id="s1",
        source_title="Title A",
        source_locator="Methods",
        extracted_text="Text snippet",
    )
    claim = ResearchClaim(
        claim_id="c1",
        claim_text="Fact snippet",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["e1"],
    )

    result = ResearchResult(
        goal=goal,
        executive_synthesis="No identical prior art found.",
        key_findings=["Paper A is closest match."],
        closest_sources=[src],
        evidence_map={"e1": ev},
        claims=[claim],
        uncertainties=["Proprietary industry implementations."],
        status=ResearchStatus.COMPLETED,
    )
    assert result.status == ResearchStatus.COMPLETED
    assert len(result.closest_sources) == 1
    assert "e1" in result.evidence_map
