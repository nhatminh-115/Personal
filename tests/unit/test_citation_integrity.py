"""Unit tests for Citation and Evidence Provenance validation."""

import pytest
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchSource,
)
from app.research.provenance import CitationValidationError, CitationValidator


@pytest.fixture
def sample_research_graph():
    source = ResearchSource(
        source_id="src_001",
        canonical_id="arxiv:2308.1001",
        title="Stateful Multi-Turn Agent Workflows",
    )
    evidence = EvidenceItem(
        evidence_id="ev_001",
        source_id="src_001",
        source_title="Stateful Multi-Turn Agent Workflows",
        source_locator="Section: methods",
        extracted_text="Nodes reside purely in volatile memory without durable checkpoints.",
    )
    return {"src_001": source}, {"ev_001": evidence}


def test_valid_factual_claim_passes_validation(sample_research_graph):
    sources, evidence_map = sample_research_graph
    claim = ResearchClaim(
        claim_id="cl_01",
        claim_text="Paper 1 uses purely volatile memory for graph nodes.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )

    valid, err = CitationValidator.validate_claim(claim, evidence_map, sources)
    assert valid is True
    assert err is None


def test_factual_claim_without_evidence_fails_validation(sample_research_graph):
    sources, evidence_map = sample_research_graph
    claim = ResearchClaim(
        claim_id="cl_02",
        claim_text="Paper 1 was evaluated on 50 benchmarks.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=[],
    )

    # In strict mode, raises CitationValidationError
    with pytest.raises(CitationValidationError, match="has no associated evidence IDs"):
        CitationValidator.validate_claim(claim, evidence_map, sources, strict=True)

    # In non-strict mode, returns False with reason
    valid, reason = CitationValidator.validate_claim(claim, evidence_map, sources, strict=False)
    assert valid is False
    assert "no associated evidence IDs" in reason


def test_nonexistent_evidence_id_fails_validation(sample_research_graph):
    sources, evidence_map = sample_research_graph
    claim = ResearchClaim(
        claim_id="cl_03",
        claim_text="Paper 1 suffers from network partition vulnerabilities.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_nonexistent_999"],
    )

    with pytest.raises(CitationValidationError, match="references nonexistent evidence ID"):
        CitationValidator.validate_claim(claim, evidence_map, sources, strict=True)

    valid, reason = CitationValidator.validate_claim(claim, evidence_map, sources, strict=False)
    assert valid is False
    assert "references nonexistent evidence ID 'ev_nonexistent_999'" in reason


def test_evidence_pointing_to_nonexistent_source_fails_validation():
    sources = {}  # Empty sources
    evidence_map = {
        "ev_orphan": EvidenceItem(
            evidence_id="ev_orphan",
            source_id="src_missing",
            source_title="Missing Source",
            source_locator="Intro",
            extracted_text="Orphaned evidence",
        )
    }
    claim = ResearchClaim(
        claim_id="cl_04",
        claim_text="Some claim",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_orphan"],
    )

    with pytest.raises(CitationValidationError, match="references nonexistent source ID"):
        CitationValidator.validate_claim(claim, evidence_map, sources, strict=True)


def test_inferences_and_hypotheses_segregated_from_facts(sample_research_graph):
    sources, evidence_map = sample_research_graph
    fact = ResearchClaim(
        claim_id="c_fact",
        claim_text="Graph nodes reside in volatile memory.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )
    inf = ResearchClaim(
        claim_id="c_inf",
        claim_text="This volatile architecture is dangerous for cloud deployments.",
        claim_type=ClaimType.SPECIALIST_INFERENCE,
        evidence_ids=["ev_001"],
    )
    hypo = ResearchClaim(
        claim_id="c_hypo",
        claim_text="Adding WAL checkpoints would eliminate crash data loss.",
        claim_type=ClaimType.HYPOTHESIS,
    )
    bad_fact = ResearchClaim(
        claim_id="c_bad",
        claim_text="Unsupported assertion without evidence.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=[],
    )

    claims = [fact, inf, hypo, bad_fact]
    res = CitationValidator.validate_all(claims, evidence_map, sources, strict=False)

    assert res["is_valid"] is False
    assert res["total_claims"] == 4
    assert res["verified_facts_count"] == 1
    assert res["inferences_count"] == 1
    assert res["hypotheses_count"] == 1
    assert res["unsupported_count"] == 1
    assert res["unsupported_rate"] == 0.25
    assert len(res["unsupported_claims"]) == 1
    assert res["unsupported_claims"][0][0].claim_id == "c_bad"


def test_build_evidence_graph_links_properly(sample_research_graph):
    sources, evidence_map = sample_research_graph
    claim = ResearchClaim(
        claim_id="cl_01",
        claim_text="Volatile nodes without checkpoints.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )

    graph = CitationValidator.build_evidence_graph(sources, evidence_map, [claim])
    nodes = graph["nodes"]
    edges = graph["edges"]

    assert len(nodes) == 3  # 1 source, 1 evidence, 1 claim
    assert len(edges) == 2  # source->evidence, evidence->claim

    edge_types = [e["relation"] for e in edges]
    assert "contains_evidence" in edge_types
    assert "supports_claim" in edge_types


def test_validate_all_sources_and_sources_map_identical_behavior(sample_research_graph):
    """Regression test proving sources_map= and sources= produce identical verification results."""
    from app.research.provenance import validate_research_result, validate_research_state
    from app.research.models import ResearchResult, ResearchState, ResearchGoal

    sources, evidence_map = sample_research_graph
    fact = ResearchClaim(
        claim_id="cl_fact_1",
        claim_text="Nodes reside purely in volatile memory without durable checkpoints.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )
    inf = ResearchClaim(
        claim_id="cl_inf_1",
        claim_text="System cannot tolerate power loss.",
        claim_type=ClaimType.SPECIALIST_INFERENCE,
        evidence_ids=["ev_001"],
    )
    claims = [fact, inf]

    res_via_sources_map = CitationValidator.validate_all(
        claims=claims,
        evidence_map=evidence_map,
        sources_map=sources,
        strict=False,
    )
    res_via_sources = CitationValidator.validate_all(
        claims=claims,
        evidence_map=evidence_map,
        sources=sources,
        strict=False,
    )

    assert res_via_sources["is_valid"] is True
    assert res_via_sources["verified_facts_count"] == 1
    assert res_via_sources["inferences_count"] == 1
    assert res_via_sources["unsupported_count"] == 0
    assert len(res_via_sources["verified_facts"]) == 1
    assert res_via_sources["verified_facts"][0].verification_status == "verified"

    # Strict equivalence of both invocation forms
    assert res_via_sources_map["is_valid"] == res_via_sources["is_valid"]
    assert res_via_sources_map["verified_facts_count"] == res_via_sources["verified_facts_count"]
    assert res_via_sources_map["inferences_count"] == res_via_sources["inferences_count"]
    assert res_via_sources_map["unsupported_count"] == res_via_sources["unsupported_count"]
    assert res_via_sources_map["referenced_evidence_ids"] == res_via_sources["referenced_evidence_ids"]
    assert res_via_sources_map["referenced_source_ids"] == res_via_sources["referenced_source_ids"]


def test_valid_factual_claim_remains_verified_with_sources_kwarg(sample_research_graph):
    """Reproduces the exact bug where sources= previously caused claims to become unsupported."""
    sources, evidence_map = sample_research_graph
    claim = ResearchClaim(
        claim_id="cl_factual_valid",
        claim_text="Paper 1 uses purely volatile memory without durable checkpoints.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )

    # Invocation with sources= keyword argument (exactly how runtime invoked it)
    eval_result = CitationValidator.validate_all(
        claims=[claim],
        evidence_map=evidence_map,
        sources=sources,
        strict=False,
    )

    assert eval_result["is_valid"] is True
    assert eval_result["unsupported_count"] == 0
    assert eval_result["verified_facts_count"] == 1
    assert claim.verification_status == "verified"
    assert "ev_001" in eval_result["referenced_evidence_ids"]
    assert "src_001" in eval_result["referenced_source_ids"]


def test_canonical_validate_research_helpers(sample_research_graph):
    """Verifies that validate_research_state and validate_research_result share identical semantics."""
    from app.research.provenance import validate_research_result, validate_research_state
    from app.research.models import ResearchGoal, ResearchResult, ResearchState

    sources, evidence_map = sample_research_graph
    claim = ResearchClaim(
        claim_id="cl_fact_help",
        claim_text="Paper 1 uses purely volatile memory without durable checkpoints.",
        claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
        evidence_ids=["ev_001"],
    )
    goal = ResearchGoal(goal_id="g1", user_query="Investigate architectures")

    state = ResearchState(
        goal=goal,
        sources=sources,
        evidence=evidence_map,
        claims=[claim],
    )
    res_state = validate_research_state(state)
    assert res_state["is_valid"] is True
    assert res_state["verified_facts_count"] == 1

    result = ResearchResult(
        goal=goal,
        executive_synthesis="Test synthesis",
        key_findings=["Finding"],
        closest_sources=list(sources.values()),
        evidence_map=evidence_map,
        claims=[claim],
    )
    res_result = validate_research_result(result)
    assert res_result["is_valid"] is True
    assert res_result["verified_facts_count"] == 1
