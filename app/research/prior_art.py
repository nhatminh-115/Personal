"""Prior art and novelty investigation workflow for research specialists."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.research.models import ResearchResult, ResearchSource


class RelatedWorkComparison(BaseModel):
    """Detailed technical comparison against an individual prior art work."""

    source_id: str
    title: str
    canonical_id: str
    what_it_does: str
    exact_overlap: str
    exact_differences: str
    overlap_risk_assessment: str  # "high", "moderate", "low", "different_objective"


class PriorArtReport(BaseModel):
    """Structured report produced by the research_prior_art workflow."""

    project_name: str
    proposed_idea: str
    executive_assessment: str
    closest_related_works: List[RelatedWorkComparison] = Field(default_factory=list)
    evidence_backed_research_gap: Optional[str] = None
    unresolved_risk_of_overlap: Optional[str] = None
    search_limitations: List[str] = Field(default_factory=list)
    recommended_next_searches: List[str] = Field(default_factory=list)


def format_prior_art_prompt(
    project_name: str,
    proposed_idea: str,
    keywords: Optional[List[str]] = None,
    date_constraints: Optional[str] = None,
) -> str:
    """Format the canonical prompt instruction for prior art research."""
    kw_str = f" Keywords: {', '.join(keywords)}." if keywords else ""
    date_str = f" Date constraints: {date_constraints}." if date_constraints else ""
    return (
        f"[PRIOR ART INVESTIGATION] Project: '{project_name}'.{kw_str}{date_str}\n"
        f"Proposed Architecture / Idea:\n{proposed_idea}\n\n"
        "Instructions for Research Specialist:\n"
        "1. Issue search queries exploring related methods, architectures, and terminology.\n"
        "2. Inspect candidate papers, focusing explicitly on the Methods and Limitations sections.\n"
        "3. Extract concrete evidence items with locator details.\n"
        "4. Conduct a second search iteration to explore any missing mechanisms or related systems.\n"
        "5. Distinguish exact technical overlap from superficial terminology similarity.\n"
        "6. Do NOT declare a binary 'novel / not novel' verdict. Qualify findings with evidence:\n"
        "   - Identify what each work actually does.\n"
        "   - State the exact overlap and the exact differences.\n"
        "   - Document any unresolved risk of overlap or evidence-backed research gaps.\n"
        "7. Store validated findings in project memory with evidence citations."
    )
