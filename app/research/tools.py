"""Scoped research tools for literature search, document reading, evidence extraction, and claim recording."""

import uuid
from typing import Any, Dict, List, Optional
from app.approvals.capabilities import Capability
from app.research.corpus import corpus_engine
from app.research.dedup import SourceDeduplicator
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchSource,
    SourceStatus,
)
from app.tools.base import RiskLevel, Tool, ToolResult


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
        raw_results = corpus_engine.search(query, max_results=max_results)

        # Deduplicate results
        deduped = SourceDeduplicator.deduplicate(raw_results, existing_sources={})

        if not deduped:
            return ToolResult(
                success=True,
                output=f"No matching sources found for query: '{query}'. Consider broadening or adjusting keywords.",
                metadata={"query": query, "count": 0, "sources": []},
            )

        lines = [f"Found {len(deduped)} candidate source(s) for query: '{query}':\n"]
        for idx, s in enumerate(deduped, 1):
            lines.append(
                f"[{idx}] Source ID: {s.source_id}\n"
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
                "count": len(deduped),
                "sources": [s.model_dump() for s in deduped],
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

        src = corpus_engine.get_source(source_id)
        if not src:
            return ToolResult(
                success=False,
                output="",
                error=f"Source '{source_id}' not found in research repository.",
            )

        section_content = src.sections.get(section_name)
        if not section_content:
            avail = list(src.sections.keys())
            return ToolResult(
                success=False,
                output="",
                error=f"Section '{section_name}' not present in '{src.title}'. Available sections: {avail}",
            )

        output_text = (
            f"=== {src.title} ===\n"
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
    """Extracts an atomic, verifiable snippet of evidence from a source with locator provenance."""

    @property
    def name(self) -> str:
        return "extract_evidence"

    @property
    def description(self) -> str:
        return (
            "Record an extracted piece of evidence from a researched source with explicit locator "
            "(e.g. 'Section: methods', 'Page 3') and confidence score."
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
                    "description": "Specific location of the evidence (e.g. 'Section: methods', 'Page 4, Col 2').",
                },
                "extracted_text": {
                    "type": "string",
                    "description": "Exact excerpt or normalized textual evidence.",
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

        src = corpus_engine.get_source(source_id)
        if not src:
            return ToolResult(
                success=False,
                output="",
                error=f"Cannot extract evidence: source '{source_id}' does not exist.",
            )

        evidence_id = f"ev_{uuid.uuid4().hex[:8]}"
        evidence_item = EvidenceItem(
            evidence_id=evidence_id,
            source_id=source_id,
            source_title=src.title,
            source_locator=locator,
            extracted_text=extracted_text,
            summary=summary,
            confidence=confidence,
            metadata={"canonical_id": src.canonical_id},
        )

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
    """Records a research claim linked to evidence items with strict claim-type verification."""

    @property
    def name(self) -> str:
        return "record_research_claim"

    @property
    def description(self) -> str:
        return (
            "Record a research claim or synthesis point. Distinguishes 'source_supported_fact' (requires evidence_ids), "
            "'specialist_inference', and 'hypothesis'."
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
                    "description": "List of evidence IDs directly supporting this claim (mandatory for facts).",
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

        if claim_type == ClaimType.SOURCE_SUPPORTED_FACT and not evidence_ids:
            return ToolResult(
                success=False,
                output="",
                error="Citation Error: 'source_supported_fact' claims strictly require at least one valid 'evidence_ids'.",
            )

        claim_id = f"cl_{uuid.uuid4().hex[:8]}"
        claim = ResearchClaim(
            claim_id=claim_id,
            claim_text=claim_text,
            claim_type=claim_type,
            evidence_ids=evidence_ids,
            verification_status="verified",
            notes=notes,
        )

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
            "Scoped strictly to the designated project."
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
                "finding_content": {
                    "type": "string",
                    "description": "Synthesized finding content with comparative insights.",
                },
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidence IDs supporting this finding.",
                    "default": [],
                },
                "source_references": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Canonical source IDs or paper titles referenced.",
                    "default": [],
                },
            },
            "required": ["project_name", "key", "finding_content"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        project_name = input_data.get("project_name", "").strip()
        key = input_data.get("key", "").strip()
        content = input_data.get("finding_content", "").strip()
        evidence_ids = input_data.get("evidence_ids", [])
        source_refs = input_data.get("source_references", [])

        if not project_name or not key or not content:
            return ToolResult(success=False, output="", error="Missing required parameters (project_name, key, finding_content).")

        # Access memory service via context if provided
        memory_svc = None
        if context:
            memory_svc = context.get("memory_service") or (context.get("services", {}).get("memory_service"))
            if not memory_svc and "db" in context:
                from app.memory.service import SQLMemoryService
                memory_svc = SQLMemoryService(context["db"])

        if memory_svc:
            meta = {
                "type": "research_finding",
                "evidence_ids": evidence_ids,
                "source_references": source_refs,
            }
            stored = await memory_svc.store_project_memory(
                project_name=project_name,
                key=key,
                content=content,
                metadata=meta,
            )
            output_text = f"Stored research finding in project memory '{project_name}:{key}' (Memory ID: {stored.id})"
        else:
            output_text = f"[Simulated memory write] Project memory '{project_name}:{key}' staged with {len(evidence_ids)} evidence citations."

        return ToolResult(
            success=True,
            output=output_text,
            metadata={
                "project_name": project_name,
                "key": key,
                "evidence_ids": evidence_ids,
                "source_references": source_refs,
            },
        )
