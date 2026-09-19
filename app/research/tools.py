"""Scoped research tools for literature search, document reading, evidence extraction, and claim recording."""

import re
import uuid
from typing import Any, Dict, List, Optional
from app.approvals.capabilities import Capability
from app.research.dedup import SourceDeduplicator
from app.research.factory import get_default_research_provider
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchQuery,
    ResearchSource,
    ResearchState,
    ResearchStatus,
    SourceStatus,
)
from app.research.provider import ResearchSourceProvider
from app.research.provenance import CitationValidationError, CitationValidator
from app.tools.base import RiskLevel, Tool, ToolResult


def _extract_research_provider(context: Optional[Dict[str, Any]]) -> ResearchSourceProvider:
    """Resolve active ResearchSourceProvider from execution context or fallback to default factory."""
    if context:
        prov = context.get("research_provider")
        if not prov and "services" in context and isinstance(context["services"], dict):
            prov = context["services"].get("research_provider")
        if prov and isinstance(prov, ResearchSourceProvider):
            return prov
    return get_default_research_provider()


def normalize_snippet(text: str) -> str:
    """Normalize text whitespace and lowercase for substring grounding check."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _extract_research_state(context: Optional[Dict[str, Any]]) -> Optional[ResearchState]:
    """Safely extract typed ResearchState from execution context if present."""
    if not context or "research_state" not in context:
        return None
    r_dict = context["research_state"]
    if isinstance(r_dict, dict):
        return ResearchState.from_dict(r_dict)
    elif isinstance(r_dict, ResearchState):
        return r_dict
    return None


def _sync_research_state(r_state: ResearchState, context: Optional[Dict[str, Any]]) -> None:
    """Synchronize updated ResearchState back into context dict for checkpoint persistence."""
    if context and "research_state" in context and isinstance(context["research_state"], dict):
        context["research_state"].clear()
        context["research_state"].update(r_state.to_dict())


class ResearchSearchTool(Tool):
    """Searches academic and technical literature across the research corpus."""

    @property
    def name(self) -> str:
        return "research_search"

    @property
    def description(self) -> str:
        return (
            "Search technical literature, papers, and architecture documents. "
            "Returns canonical sources with abstract summaries and relevance scores."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.MCP_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Target search query, keywords, or architectural concepts to investigate.",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["broad", "narrow", "exact", "method", "closest_overlap"],
                    "description": "Strategy for query matching.",
                    "default": "broad",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of candidate sources to return.",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        query = input_data.get("query", "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Missing required parameter 'query'.")

        max_results = int(input_data.get("max_results", 5))
        search_type = input_data.get("search_type", "broad")
        provider = _extract_research_provider(context)
        raw_results = await provider.search(query, search_type=search_type, max_results=max_results)

        r_state = _extract_research_state(context)
        existing_sources = dict(r_state.sources) if r_state else {}

        # Deduplicate results against existing sources in the shared research state
        distinct_new = SourceDeduplicator.deduplicate(raw_results, existing_sources=existing_sources)

        if r_state:
            # Register query execution into durable research state
            query_record = ResearchQuery(
                query_id=f"qry_{uuid.uuid4().hex[:6]}",
                query_text=query,
                search_type=search_type,
                iteration=r_state.current_iteration,
                results_count=len(raw_results),
            )
            r_state.register_query(query_record)

            # Register all updated/new sources into research state
            for s in existing_sources.values():
                r_state.upsert_source(s)
            _sync_research_state(r_state, context)

        all_candidate_sources = list(existing_sources.values()) if existing_sources else distinct_new

        if not all_candidate_sources:
            return ToolResult(
                success=True,
                output=f"No matching sources found for query: '{query}'. Consider broadening or adjusting keywords.",
                metadata={"query": query, "count": 0, "sources": []},
            )

        lines = [f"Found {len(all_candidate_sources)} candidate source(s) for query: '{query}':\n"]
        for idx, s in enumerate(all_candidate_sources, 1):
            fixture_tag = " [deterministic research fixture]" if s.metadata.get("fixture") else ""
            lines.append(
                f"[{idx}] Source ID: {s.source_id}{fixture_tag}\n"
                f"    Canonical ID: {s.canonical_id}\n"
                f"    Title: {s.title} ({s.year or 'N/A'})\n"
                f"    Authors: {', '.join(s.authors[:3])}\n"
                f"    Relevance: {s.relevance_score}\n"
                f"    Abstract: {(s.abstract or 'No abstract')[:200]}...\n"
            )

        return ToolResult(
            success=True,
            output="\n".join(lines),
            metadata={
                "query": query,
                "count": len(all_candidate_sources),
                "new_count": len(distinct_new),
                "sources": [s.model_dump() for s in all_candidate_sources],
                "iteration": r_state.current_iteration if r_state else 1,
            },
        )


class ReadDocumentSectionTool(Tool):
    """Reads specific full-text sections of a research paper or technical document."""

    @property
    def name(self) -> str:
        return "read_document_section"

    @property
    def description(self) -> str:
        return (
            "Read a specific section (e.g. 'methods', 'introduction', 'abstract', 'results', 'limitations') "
            "of an identified research source to inspect technical mechanisms and fine details."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.MCP_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Identifier of the source to inspect (e.g. 'src_stateful_graph_2023').",
                },
                "section_name": {
                    "type": "string",
                    "enum": ["abstract", "introduction", "related_work", "methods", "experiments", "results", "limitations"],
                    "description": "Name of the paper section to read.",
                    "default": "methods",
                },
            },
            "required": ["source_id", "section_name"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        source_id = input_data.get("source_id", "").strip()
        section_name = input_data.get("section_name", "methods").strip().lower()

        r_state = _extract_research_state(context)
        provider = _extract_research_provider(context)
        src = None
        if r_state and source_id in r_state.sources:
            src = r_state.sources[source_id]
        if not src:
            src = await provider.fetch_source(source_id)
            if src and r_state:
                r_state.upsert_source(src)

        if not src:
            return ToolResult(
                success=False,
                output="",
                error=f"Source '{source_id}' not found in research repository.",
            )

        section_content = src.sections.get(section_name)
        if not section_content:
            # Dynamically fetch section from active provider (e.g. download PDF or parse section)
            section_content = await provider.fetch_section(source_id, section_name)
            if section_content:
                src.sections[section_name] = section_content
                if r_state:
                    r_state.upsert_source(src)

        if not section_content:
            avail = list(src.sections.keys())
            return ToolResult(
                success=False,
                output="",
                error=f"Section '{section_name}' not present in '{src.title}'. Available sections: {avail}",
            )

        # Mark source as inspected in research state
        if r_state:
            r_state.mark_source_inspected(source_id)
            _sync_research_state(r_state, context)

        fixture_tag = " [deterministic research fixture]" if src.metadata.get("fixture") else ""
        output_text = (
            f"=== {src.title}{fixture_tag} ===\n"
            f"Canonical ID: {src.canonical_id}\n"
            f"Section: {section_name.upper()}\n"
            f"----------------------------------------\n"
            f"{section_content}\n"
        )

        return ToolResult(
            success=True,
            output=output_text,
            metadata={
                "source_id": source_id,
                "source_title": src.title,
                "canonical_id": src.canonical_id,
                "section_name": section_name,
                "content_length": len(section_content),
            },
        )


class ExtractEvidenceTool(Tool):
    """Extracts an atomic, verifiable snippet of evidence from a source with locator provenance and source grounding."""

    @property
    def name(self) -> str:
        return "extract_evidence"

    @property
    def description(self) -> str:
        return (
            "Record an extracted piece of evidence from a researched source with explicit locator "
            "(e.g. 'Section: methods', 'Page 3') and confidence score. The extracted text is strictly grounded against source text."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.MCP_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Identifier of the source where evidence was extracted.",
                },
                "locator": {
                    "type": "string",
                    "description": "Specific location of the evidence (e.g. 'Section: methods', 'methods').",
                },
                "extracted_text": {
                    "type": "string",
                    "description": "Exact excerpt or verbatim span from the source.",
                },
                "summary": {
                    "type": "string",
                    "description": "Brief explanation of what this evidence demonstrates.",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score between 0.0 and 1.0.",
                    "default": 1.0,
                },
            },
            "required": ["source_id", "locator", "extracted_text"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        source_id = input_data.get("source_id", "").strip()
        locator = input_data.get("locator", "").strip()
        extracted_text = input_data.get("extracted_text", "").strip()
        summary = input_data.get("summary")
        confidence = float(input_data.get("confidence", 1.0))

        if not source_id or not locator or not extracted_text:
            return ToolResult(
                success=False,
                output="",
                error="Missing required parameters (source_id, locator, extracted_text).",
            )

        r_state = _extract_research_state(context)
        provider = _extract_research_provider(context)
        src = None
        if r_state and source_id in r_state.sources:
            src = r_state.sources[source_id]
        if not src:
            src = await provider.fetch_source(source_id)
            if src and r_state:
                r_state.upsert_source(src)

        if not src:
            return ToolResult(
                success=False,
                output="",
                error=f"Cannot extract evidence: source '{source_id}' does not exist.",
            )

        # Grounding check: verify that normalized extracted_text appears in the source section
        norm_extracted = normalize_snippet(extracted_text)
        grounded = False

        # Attempt to match against specific locator section first
        loc_lower = locator.lower()
        matched_section_name = None
        for sec_name in src.sections:
            if sec_name in loc_lower:
                matched_section_name = sec_name
                break

        if matched_section_name and matched_section_name in src.sections:
            norm_sec = normalize_snippet(src.sections[matched_section_name])
            if norm_extracted in norm_sec:
                grounded = True

        # Fallback: check across all sections of the source
        if not grounded:
            for sec_name, sec_content in src.sections.items():
                if norm_extracted in normalize_snippet(sec_content):
                    grounded = True
                    break

        if not grounded:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Grounding validation failed: The extracted text was not found in source '{src.title}' "
                    f"({source_id}) at locator '{locator}'. Fabricated or ungrounded evidence is strictly rejected."
                ),
            )

        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        evidence_item = EvidenceItem(
            evidence_id=evidence_id,
            source_id=src.source_id,
            source_title=src.title,
            source_locator=locator,
            extracted_text=extracted_text,
            summary=summary,
            confidence=confidence,
            metadata={"canonical_id": src.canonical_id, "grounded": True},
        )

        if r_state:
            r_state.register_evidence(evidence_item)
            _sync_research_state(r_state, context)

        output_text = (
            f"Successfully recorded Evidence '{evidence_id}':\n"
            f"  Source: {src.title} ({src.canonical_id})\n"
            f"  Locator: {locator}\n"
            f"  Evidence: {extracted_text[:120]}..."
        )

        return ToolResult(
            success=True,
            output=output_text,
            metadata={"evidence": evidence_item.model_dump(), "evidence_id": evidence_id},
        )


class RecordResearchClaimTool(Tool):
    """Records a research claim linked to evidence items with strict claim-type and citation verification."""

    @property
    def name(self) -> str:
        return "record_research_claim"

    @property
    def description(self) -> str:
        return (
            "Record a research claim or synthesis point. Distinguishes 'source_supported_fact' (requires evidence_ids), "
            "'specialist_inference', and 'hypothesis'. Factual claims strictly validate evidence IDs against the registry."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.MCP_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "claim_text": {
                    "type": "string",
                    "description": "The factual claim, inference, or hypothesis statement.",
                },
                "claim_type": {
                    "type": "string",
                    "enum": ["source_supported_fact", "specialist_inference", "hypothesis"],
                    "description": "Epistemological category of the claim.",
                    "default": "source_supported_fact",
                },
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of authoritative evidence IDs directly supporting this claim (mandatory for facts).",
                    "default": [],
                },
                "notes": {
                    "type": "string",
                    "description": "Optional qualifying remarks or contextual caveats.",
                },
            },
            "required": ["claim_text", "claim_type"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        claim_text = input_data.get("claim_text", "").strip()
        claim_type_str = input_data.get("claim_type", "source_supported_fact").strip()
        evidence_ids = input_data.get("evidence_ids", [])
        notes = input_data.get("notes")

        if not claim_text:
            return ToolResult(success=False, output="", error="Missing required parameter 'claim_text'.")

        try:
            claim_type = ClaimType(claim_type_str)
        except ValueError:
            return ToolResult(
                success=False,
                output="",
                error=f"Invalid claim_type '{claim_type_str}'. Must be one of: {[e.value for e in ClaimType]}",
            )

        r_state = _extract_research_state(context)
        evidence_map = dict(r_state.evidence) if r_state else {}
        sources_map = dict(r_state.sources) if r_state else {}

        claim_id = f"cl_{uuid.uuid4().hex[:8]}"
        claim = ResearchClaim(
            claim_id=claim_id,
            claim_text=claim_text,
            claim_type=claim_type,
            evidence_ids=evidence_ids,
            verification_status="unsupported",
            notes=notes,
        )

        # Enforce CitationValidator in production claim recording path
        try:
            is_valid, reason = CitationValidator.validate_claim(
                claim,
                evidence_map=evidence_map,
                sources=sources_map,
                strict=True,
            )
            if not is_valid:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Citation validation error: {reason}",
                    metadata={"claim_text": claim_text, "reason": reason},
                )
        except CitationValidationError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Citation validation error: {exc}",
                metadata={"claim_text": claim_text, "invalid_evidence_ids": evidence_ids},
            )

        # Mark claim verified only after passing validation
        claim.verification_status = "verified"

        if r_state:
            r_state.register_claim(claim)
            _sync_research_state(r_state, context)

        output_text = (
            f"Successfully recorded Research Claim '{claim_id}' [{claim_type.value}]:\n"
            f"  Text: {claim_text}\n"
            f"  Supporting Evidence: {evidence_ids or 'None (Inference/Hypothesis)'}"
        )

        return ToolResult(
            success=True,
            output=output_text,
            metadata={"claim": claim.model_dump(), "claim_id": claim_id},
        )


class SaveResearchFindingTool(Tool):
    """Persists a high-value validated research finding to the project-scoped memory store."""

    @property
    def name(self) -> str:
        return "save_research_finding"

    @property
    def description(self) -> str:
        return (
            "Save a validated, durable research finding into project memory with full citation metadata. "
            "Scoped strictly to the designated project. Strictly validates evidence IDs and source references before persistence."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.MCP_READ.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project identifier (e.g. 'Atlas_Architecture').",
                },
                "key": {
                    "type": "string",
                    "description": "Unique topic or finding key (e.g. 'prior_art_stateful_llm').",
                },
                "claim_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Authoritative validated ResearchClaim IDs supporting this finding.",
                    "default": [],
                },
                "finding_content": {
                    "type": "string",
                    "description": "Synthesized finding content with comparative insights derived from validated claims.",
                },
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Authoritative evidence IDs supporting this finding.",
                    "default": [],
                },
                "source_references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Canonical source IDs or paper titles referenced.",
                    "default": [],
                },
            },
            "required": ["project_name", "key"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        project_name = input_data.get("project_name", "").strip()
        key = input_data.get("key", "").strip()
        content = input_data.get("finding_content", "").strip()
        claim_ids = input_data.get("claim_ids", [])
        evidence_ids = list(input_data.get("evidence_ids", []))
        source_refs = list(input_data.get("source_references", []))

        if not project_name or not key:
            return ToolResult(success=False, output="", error="Missing required parameters (project_name, key).")

        r_state = _extract_research_state(context)
        validated_claims = []

        # Gate memory write: require and validate ResearchClaim linkage
        if r_state:
            if claim_ids:
                for cid in claim_ids:
                    matched = next((c for c in r_state.claims if c.claim_id == cid), None)
                    if not matched:
                        return ToolResult(
                            success=False,
                            output="",
                            error=f"Memory write rejected: claim ID '{cid}' not found in active claims registry.",
                            metadata={"invalid_claim_id": cid},
                        )
                    if matched.verification_status != "verified":
                        return ToolResult(
                            success=False,
                            output="",
                            error=f"Memory write rejected: claim ID '{cid}' is unverified ({matched.verification_status}). Only verified claims can enter project memory.",
                            metadata={"unverified_claim_id": cid},
                        )
                    validated_claims.append(matched)
            else:
                if evidence_ids:
                    matched = [
                        c for c in r_state.claims
                        if c.verification_status == "verified" and any(eid in c.evidence_ids for eid in evidence_ids)
                    ]
                    if not matched:
                        return ToolResult(
                            success=False,
                            output="",
                            error="Memory write rejected: No verified ResearchClaim found supporting these evidence citations. Persisted findings must be derived from validated claims.",
                            metadata={"evidence_ids": evidence_ids},
                        )
                    validated_claims.extend(matched)
                elif r_state.claims:
                    validated_claims = [c for c in r_state.claims if c.verification_status == "verified"]

            # Merge evidence_ids from validated claims
            for c in validated_claims:
                for eid in c.evidence_ids:
                    if eid not in evidence_ids:
                        evidence_ids.append(eid)

            # Validate all evidence_ids against active evidence registry
            for ev_id in evidence_ids:
                if ev_id not in r_state.evidence:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Memory write rejected: evidence ID '{ev_id}' not found in active evidence registry.",
                        metadata={"invalid_evidence_id": ev_id},
                    )

            # Auto-populate and validate source references
            for ev_id in evidence_ids:
                sid = r_state.evidence[ev_id].source_id
                if sid not in source_refs:
                    source_refs.append(sid)

            known_sources = r_state.sources
            for sref in source_refs:
                matched = any(
                    sref in (s.source_id, s.canonical_id, s.url, s.title) or sref in s.aliases
                    for s in known_sources.values()
                )
                if not matched:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Memory write rejected: source reference '{sref}' not found in active source registry.",
                        metadata={"invalid_source_ref": sref},
                    )

        if not content:
            if validated_claims:
                content = "\n".join([f"- [{c.claim_type.value}] {c.claim_text}" for c in validated_claims])
            else:
                return ToolResult(success=False, output="", error="Missing required parameter 'finding_content' and no validated claims to derive from.")

        # Guard against overclaiming "verified research gap"
        lower_content = content.lower()
        gap_phrases = ["verified research gap", "verified gap", "proven gap", "proven research gap"]
        if any(gp in lower_content for gp in gap_phrases):
            has_validated_gap_claim = any(
                c.verification_status == "verified" and
                c.claim_type in (ClaimType.SPECIALIST_INFERENCE, ClaimType.SOURCE_SUPPORTED_FACT) and
                any(w in c.claim_text.lower() for w in ["gap", "novelty", "unaddressed"])
                for c in validated_claims
            )
            is_insufficient = (r_state.status == ResearchStatus.INSUFFICIENT_EVIDENCE) if r_state else True
            if is_insufficient or not has_validated_gap_claim:
                return ToolResult(
                    success=False,
                    output="",
                    error="Memory write rejected: Finding asserts 'verified research gap', but research status is insufficient_evidence or no validated gap claim exists.",
                    metadata={"overclaiming_terms": [gp for gp in gap_phrases if gp in lower_content]},
                )

        # Build compact evidence snapshot for long-term interpretability
        evidence_snapshot = []
        if r_state:
            for ev_id in evidence_ids:
                ev = r_state.evidence[ev_id]
                evidence_snapshot.append({
                    "evidence_id": ev.evidence_id,
                    "source_id": ev.source_id,
                    "source_title": ev.source_title,
                    "canonical_id": ev.metadata.get("canonical_id", ""),
                    "locator": ev.source_locator,
                    "snippet": (ev.extracted_text[:120] + "...") if len(ev.extracted_text) > 120 else ev.extracted_text,
                    "confidence": ev.confidence,
                })

        # Access memory service via context if provided
        memory_svc = None
        if context:
            memory_svc = context.get("memory_service") or (context.get("services", {}).get("memory_service"))
            if not memory_svc and "db" in context:
                from app.memory.service import SQLMemoryService
                memory_svc = SQLMemoryService(context["db"])

        stored_claim_ids = [c.claim_id for c in validated_claims]
        meta = {
            "type": "research_finding",
            "project_name": project_name,
            "claim_ids": stored_claim_ids,
            "evidence_ids": evidence_ids,
            "source_references": source_refs,
            "evidence_snapshot": evidence_snapshot,
            "confidence": 0.95,
            "created_by": "research_specialist",
        }

        if memory_svc:
            stored = await memory_svc.store_project_memory(
                project_name=project_name,
                key=key,
                content=content,
                metadata=meta,
            )
            output_text = f"Stored research finding in project memory '{project_name}:{key}' (Memory ID: {stored.id})"
        else:
            output_text = f"[Simulated memory write] Project memory '{project_name}:{key}' staged with {len(evidence_ids)} evidence citations and {len(stored_claim_ids)} claim citations."

        return ToolResult(
            success=True,
            output=output_text,
            metadata={
                "project_name": project_name,
                "key": key,
                "claim_ids": stored_claim_ids,
                "evidence_ids": evidence_ids,
                "source_references": source_refs,
                "evidence_snapshot": evidence_snapshot,
            },
        )
