"""Unit tests for source grounding verification in ExtractEvidenceTool."""

import pytest
from app.research.corpus import corpus_engine
from app.research.models import ResearchState
from app.research.tools import ExtractEvidenceTool


@pytest.mark.asyncio
async def test_verbatim_grounded_evidence_succeeds():
    tool = ExtractEvidenceTool()
    context = {"research_state": ResearchState().to_dict()}

    # Extract verbatim quote from Paper 1 (src_stateful_graph_2023)
    res = await tool.execute(
        {
            "source_id": "src_stateful_graph_2023",
            "locator": "Section: methods",
            "extracted_text": "Our method maintains an active execution graph in memory with volatile node state transitions.",
            "summary": "Verbatim quote demonstrating in-memory execution graph.",
        },
        context=context,
    )

    assert res.success is True
    assert "Successfully recorded Evidence" in res.output
    ev_id = res.metadata["evidence_id"]
    assert ev_id.startswith("ev_")
    assert res.metadata["evidence"]["metadata"]["grounded"] is True

    # Ensure evidence is stored in durable research_state
    r_state = ResearchState.from_dict(context["research_state"])
    assert ev_id in r_state.evidence
    assert r_state.evidence[ev_id].source_id == "src_stateful_graph_2023"


@pytest.mark.asyncio
async def test_fabricated_evidence_fails_grounding_check():
    tool = ExtractEvidenceTool()
    context = {"research_state": ResearchState().to_dict()}

    # Fabricated claim not present in the paper
    res = await tool.execute(
        {
            "source_id": "src_stateful_graph_2023",
            "locator": "Section: methods",
            "extracted_text": "This paper implements quantum annealing hardware acceleration on superconducting qubits.",
            "summary": "Fabricated text about quantum annealing.",
        },
        context=context,
    )

    assert res.success is False
    assert "Grounding validation failed" in res.error
    assert "Fabricated or ungrounded evidence is strictly rejected" in res.error

    # Ensure NO EvidenceItem was registered in research_state
    r_state = ResearchState.from_dict(context["research_state"])
    assert len(r_state.evidence) == 0


@pytest.mark.asyncio
async def test_nonexistent_source_id_fails():
    tool = ExtractEvidenceTool()
    context = {"research_state": ResearchState().to_dict()}

    res = await tool.execute(
        {
            "source_id": "src_imaginary_fake_paper_2099",
            "locator": "Section: methods",
            "extracted_text": "Some text",
        },
        context=context,
    )

    assert res.success is False
    assert "does not exist" in res.error
