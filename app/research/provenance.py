"""Citation and evidence provenance validation for research synthesis."""

from typing import Any, Dict, List, Optional, Set, Tuple
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchSource,
)


class CitationValidationError(Exception):
    """Raised when a factual research claim violates evidence provenance invariants."""
    pass


class CitationValidator:
    """Enforces strict provenance, detects fabricated citations, and categorizes claims."""

    @classmethod
    def validate_claim(
        cls,
        claim: ResearchClaim,
        evidence_map: Dict[str, EvidenceItem],
        sources_map: Optional[Dict[str, ResearchSource]] = None,
        sources: Optional[Dict[str, ResearchSource]] = None,
        strict: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """Validate an individual claim against available evidence and sources."""
        src_map = sources_map if sources_map is not None else (sources or {})
        if claim.claim_type == ClaimType.SOURCE_SUPPORTED_FACT:
            if not claim.evidence_ids:
                msg = f"Factual claim '{claim.claim_id}' has no associated evidence IDs."
                if strict:
                    raise CitationValidationError(msg)
                return False, msg

            for ev_id in claim.evidence_ids:
                if ev_id not in evidence_map:
                    msg = f"Factual claim '{claim.claim_id}' references nonexistent evidence ID '{ev_id}'."
                    if strict:
                        raise CitationValidationError(msg)
                    return False, msg

                ev_item = evidence_map[ev_id]
                if ev_item.source_id not in src_map:
                    msg = f"Evidence '{ev_id}' references nonexistent source ID '{ev_item.source_id}'."
                    if strict:
                        raise CitationValidationError(msg)
                    return False, msg

        return True, None

    @classmethod
    def validate_all(
        cls,
        claims: List[ResearchClaim],
        evidence_map: Dict[str, EvidenceItem],
        sources_map: Optional[Dict[str, ResearchSource]] = None,
        sources: Optional[Dict[str, ResearchSource]] = None,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Validate all claims, segregate facts from inferences, and report integrity score."""
        src_map = sources_map if sources_map is not None else (sources or {})
        verified_facts: List[ResearchClaim] = []
        inferences: List[ResearchClaim] = []
        hypotheses: List[ResearchClaim] = []
        unsupported_claims: List[Tuple[ResearchClaim, str]] = []

        referenced_evidence_ids: Set[str] = set()
        referenced_source_ids: Set[str] = set()

        for claim in claims:
            is_valid, reason = cls.validate_claim(claim, evidence_map, sources_map, strict=strict)
            if not is_valid:
                claim.verification_status = "unsupported"
                unsupported_claims.append((claim, reason or "Validation failure"))
                continue

            if claim.claim_type == ClaimType.SOURCE_SUPPORTED_FACT:
                claim.verification_status = "verified"
                verified_facts.append(claim)
                for eid in claim.evidence_ids:
                    referenced_evidence_ids.add(eid)
                    if eid in evidence_map:
                        referenced_source_ids.add(evidence_map[eid].source_id)
            elif claim.claim_type == ClaimType.SPECIALIST_INFERENCE:
                inferences.append(claim)
            elif claim.claim_type == ClaimType.HYPOTHESIS:
                hypotheses.append(claim)

        total_claims = len(claims)
        unsupported_count = len(unsupported_claims)
        unsupported_rate = (unsupported_count / total_claims) if total_claims > 0 else 0.0

        return {
            "is_valid": unsupported_count == 0,
            "total_claims": total_claims,
            "verified_facts_count": len(verified_facts),
            "inferences_count": len(inferences),
            "hypotheses_count": len(hypotheses),
            "unsupported_count": unsupported_count,
            "unsupported_rate": unsupported_rate,
            "verified_facts": verified_facts,
            "inferences": inferences,
            "hypotheses": hypotheses,
            "unsupported_claims": unsupported_claims,
            "referenced_evidence_ids": list(referenced_evidence_ids),
            "referenced_source_ids": list(referenced_source_ids),
        }

    @staticmethod
    def build_evidence_graph(
        sources: Dict[str, ResearchSource],
        evidence_map: Dict[str, EvidenceItem],
        claims: List[ResearchClaim],
    ) -> Dict[str, Any]:
        """Construct a structured directed graph linking Sources -> Evidence -> Claims."""
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, Any]] = []

        # 1. Source Nodes
        for s in sources.values():
            nodes.append({
                "id": s.source_id,
                "type": "source",
                "label": s.title,
                "canonical_id": s.canonical_id,
                "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            })

        # 2. Evidence Nodes & Source->Evidence Edges
        for ev in evidence_map.values():
            nodes.append({
                "id": ev.evidence_id,
                "type": "evidence",
                "label": f"{ev.source_locator}: {ev.extracted_text[:60]}...",
                "locator": ev.source_locator,
            })
            edges.append({
                "source": ev.source_id,
                "target": ev.evidence_id,
                "relation": "contains_evidence",
            })

        # 3. Claim Nodes & Evidence->Claim Edges
        for cl in claims:
            nodes.append({
                "id": cl.claim_id,
                "type": "claim",
                "claim_type": cl.claim_type.value if hasattr(cl.claim_type, "value") else str(cl.claim_type),
                "status": cl.verification_status,
                "label": cl.claim_text,
            })
            for eid in cl.evidence_ids:
                if eid in evidence_map:
                    edges.append({
                        "source": eid,
                        "target": cl.claim_id,
                        "relation": "supports_claim",
                    })

        return {"nodes": nodes, "edges": edges}
