"""Typed domain models for the AURA Research Specialist."""

from enum import Enum
import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    """Categorization of research claims enforcing provenance boundaries."""

    SOURCE_SUPPORTED_FACT = "source_supported_fact"
    SPECIALIST_INFERENCE = "specialist_inference"
    HYPOTHESIS = "hypothesis"


class SourceStatus(str, Enum):
    """Lifecycle status of candidate sources in a research run."""

    CANDIDATE = "candidate"
    SELECTED = "selected"
    INSPECTED = "inspected"
    REJECTED = "rejected"


class ResearchStatus(str, Enum):
    """Final or in-flight status of a research task."""

    RUNNING = "running"
    COMPLETED = "completed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_EXHAUSTED = "budget_exhausted"
    BLOCKED = "blocked"
    FAILED = "failed"


class ResearchGoal(BaseModel):
    """Specifies the objective and boundary constraints of a research task."""

    goal_id: str
    user_query: str
    project_name: Optional[str] = None
    research_questions: List[str] = Field(default_factory=list)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class ResearchQuery(BaseModel):
    """An individual search iteration query issued during research exploration."""

    query_id: str
    query_text: str
    search_type: str = "broad"  # "broad", "narrow", "exact", "method", "closest_overlap"
    iteration: int = 1
    rationale: str = ""
    timestamp: float = Field(default_factory=time.time)
    results_count: int = 0


class ResearchSource(BaseModel):
    """A research document, paper, or web source with canonical identification."""

    source_id: str
    canonical_id: str  # e.g., "arxiv:2305.12345", "doi:10.1145/...", or normalized title hash
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    url: Optional[str] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    sections: Dict[str, str] = Field(default_factory=dict)  # e.g. {"abstract": "...", "methods": "...", ...}
    status: SourceStatus = SourceStatus.CANDIDATE
    relevance_score: float = 0.0
    aliases: List[str] = Field(default_factory=list)  # alternate URLs or identifiers
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    """An atomic snippet of factual evidence extracted from a source with locator provenance."""

    evidence_id: str
    source_id: str
    source_title: str
    source_locator: str  # e.g. "Section 3: Methods", "Page 4, Column 2"
    extracted_text: str
    summary: Optional[str] = None
    retrieval_timestamp: float = Field(default_factory=time.time)
    confidence: float = 1.0  # 0.0 to 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ResearchClaim(BaseModel):
    """A single claim generated during research synthesis, explicitly linked to evidence."""

    claim_id: str
    claim_text: str
    claim_type: ClaimType
    evidence_ids: List[str] = Field(default_factory=list)
    verification_status: Literal["verified", "qualified", "unsupported"] = "verified"
    notes: Optional[str] = None


class ResearchResult(BaseModel):
    """Structured conclusion returned by the Research Specialist to the Root Orchestrator."""

    goal: ResearchGoal
    executive_synthesis: str
    key_findings: List[str] = Field(default_factory=list)
    closest_sources: List[ResearchSource] = Field(default_factory=list)
    evidence_map: Dict[str, EvidenceItem] = Field(default_factory=dict)
    claims: List[ResearchClaim] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)
    recommended_next_searches: List[str] = Field(default_factory=list)
    memory_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    status: ResearchStatus = ResearchStatus.COMPLETED


class ResearchState(BaseModel):
    """Durable state tracked across iterations of a Research Specialist child run."""

    goal: Optional[ResearchGoal] = None
    queries: List[ResearchQuery] = Field(default_factory=list)
    sources: Dict[str, ResearchSource] = Field(default_factory=dict)  # source_id -> ResearchSource
    evidence: Dict[str, EvidenceItem] = Field(default_factory=dict)  # evidence_id -> EvidenceItem
    claims: List[ResearchClaim] = Field(default_factory=list)
    inspected_source_ids: List[str] = Field(default_factory=list)
    status: ResearchStatus = ResearchStatus.RUNNING
    current_iteration: int = 1
    max_iterations: int = 5
