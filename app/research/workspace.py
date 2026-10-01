"""Project-graph persistence for durable Research Specialist artifacts."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel
from app.research.models import ResearchState, SourceStatus


def _stable_id(child_run_id: str, object_type: str, external_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"aura:research:{child_run_id}:{object_type}:{external_id}"))


async def persist_research_workspace_objects(
    db: AsyncSession,
    *,
    child_run_id: str,
    project_name: str,
    state: ResearchState,
) -> list[str]:
    """Persist non-rejected sources, evidence, and claims with provenance links.

    Stable object and edge IDs make retrying completion safe. Research artifacts
    are system-owned, individually selectable workspace objects; provenance
    links never expand into model context unless the user selects those objects.
    """
    sources = {
        source_id: source
        for source_id, source in state.sources.items()
        if source.status != SourceStatus.REJECTED
    }
    evidence = {
        evidence_id: item
        for evidence_id, item in state.evidence.items()
        if item.source_id in sources
    }
    source_object_ids = {
        source_id: _stable_id(child_run_id, "research_source", source_id)
        for source_id in sources
    }
    evidence_object_ids = {
        evidence_id: _stable_id(child_run_id, "research_evidence", evidence_id)
        for evidence_id in evidence
    }
    claim_object_ids = {
        claim.claim_id: _stable_id(child_run_id, "research_claim", claim.claim_id)
        for claim in state.claims
    }

    object_specs: list[WorkspaceObjectModel] = []
    for source_id, source in sources.items():
        object_specs.append(WorkspaceObjectModel(
            id=source_object_ids[source_id],
            project_name=project_name,
            object_type="research_source",
            created_by="research",
            title=source.title[:255],
            content=source.abstract or "",
            metadata_json={
                "privacy_policy": "internal",
                "research_run_id": child_run_id,
                "source_id": source.source_id,
                "canonical_id": source.canonical_id,
                "authors": source.authors,
                "year": source.year,
                "url": source.url,
                "venue": source.venue,
                "status": source.status.value,
                "relevance_score": source.relevance_score,
                "aliases": source.aliases,
            },
        ))

    for evidence_id, item in evidence.items():
        object_specs.append(WorkspaceObjectModel(
            id=evidence_object_ids[evidence_id],
            project_name=project_name,
            object_type="research_evidence",
            created_by="research",
            title=f"Evidence · {item.source_title}"[:255],
            content=item.extracted_text,
            metadata_json={
                "privacy_policy": "internal",
                "research_run_id": child_run_id,
                "evidence_id": item.evidence_id,
                "source_id": item.source_id,
                "source_object_id": source_object_ids[item.source_id],
                "source_title": item.source_title,
                "source_locator": item.source_locator,
                "confidence": item.confidence,
                "summary": item.summary,
            },
        ))

    for claim in state.claims:
        linked_evidence_ids = [
            evidence_object_ids[evidence_id]
            for evidence_id in claim.evidence_ids
            if evidence_id in evidence_object_ids
        ]
        claim_body = f"Claim type: {claim.claim_type.value}\nVerification: {claim.verification_status}\n\n{claim.claim_text}"
        if claim.notes:
            claim_body += f"\n\nQualification: {claim.notes}"
        object_specs.append(WorkspaceObjectModel(
            id=claim_object_ids[claim.claim_id],
            project_name=project_name,
            object_type="research_claim",
            created_by="research",
            title=f"{claim.claim_type.value} · {claim.claim_text}"[:255],
            content=claim_body,
            metadata_json={
                "privacy_policy": "internal",
                "research_run_id": child_run_id,
                "claim_id": claim.claim_id,
                "claim_type": claim.claim_type.value,
                "verification_status": claim.verification_status,
                "evidence_object_ids": linked_evidence_ids,
                "notes": claim.notes,
            },
        ))

    candidate_ids = [item.id for item in object_specs]
    existing_result = await db.execute(
        select(WorkspaceObjectModel.id).where(WorkspaceObjectModel.id.in_(candidate_ids))
    ) if candidate_ids else None
    existing_ids = set(existing_result.scalars()) if existing_result is not None else set()
    new_objects = [item for item in object_specs if item.id not in existing_ids]
    db.add_all(new_objects)

    edge_specs: list[WorkspaceEdgeModel] = []
    for evidence_id, item in evidence.items():
        edge_specs.append(WorkspaceEdgeModel(
            id=_stable_id(child_run_id, "source_evidence", evidence_id),
            project_name=project_name,
            source_object_id=source_object_ids[item.source_id],
            target_object_id=evidence_object_ids[evidence_id],
            relation_type="contains_evidence",
            edge_family="provenance",
            created_by="research",
            metadata_json={"research_run_id": child_run_id},
        ))
    for claim in state.claims:
        for evidence_id in claim.evidence_ids:
            evidence_object_id = evidence_object_ids.get(evidence_id)
            if evidence_object_id is None:
                continue
            edge_specs.append(WorkspaceEdgeModel(
                id=_stable_id(child_run_id, "evidence_claim", f"{evidence_id}:{claim.claim_id}"),
                project_name=project_name,
                source_object_id=evidence_object_id,
                target_object_id=claim_object_ids[claim.claim_id],
                relation_type="supports_claim",
                edge_family="provenance",
                created_by="research",
                metadata_json={"research_run_id": child_run_id},
            ))

    candidate_edge_ids = [edge.id for edge in edge_specs]
    existing_edges_result = await db.execute(
        select(WorkspaceEdgeModel.id).where(WorkspaceEdgeModel.id.in_(candidate_edge_ids))
    ) if candidate_edge_ids else None
    existing_edge_ids = set(existing_edges_result.scalars()) if existing_edges_result is not None else set()
    db.add_all(edge for edge in edge_specs if edge.id not in existing_edge_ids)
    await db.flush()
    return [item.id for item in object_specs]
