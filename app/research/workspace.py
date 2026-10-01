"""Promote validated Research Specialist outputs into the workspace graph."""

from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel
from app.research.models import ResearchState, SourceStatus
from app.research.provenance import CitationValidator


def _stable_id(kind: str, run_id: str, item_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"aura:research:{kind}:{run_id}:{item_id}"))


async def _upsert_object(
    db: AsyncSession,
    *,
    object_id: str,
    project_name: str,
    session_id: str,
    object_type: str,
    title: str,
    content: str,
    metadata: dict[str, Any],
) -> WorkspaceObjectModel:
    item = await db.get(WorkspaceObjectModel, object_id)
    if item is None:
        item = WorkspaceObjectModel(
            id=object_id,
            project_name=project_name,
            session_id=session_id,
            object_type=object_type,
            created_by="research_specialist",
            title=title[:255],
            content=content,
            metadata_json=metadata,
        )
        db.add(item)
    else:
        if item.project_name != project_name or item.session_id != session_id:
            raise ValueError("Research artifact identity is already bound to a different workspace scope.")
        item.title = title[:255]
        item.content = content
        item.metadata_json = metadata
        item.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return item


async def _upsert_provenance_edge(
    db: AsyncSession,
    *,
    run_id: str,
    project_name: str,
    source_id: str,
    target_id: str,
    relation_type: str,
) -> None:
    edge_id = _stable_id(f"edge:{relation_type}", run_id, f"{source_id}:{target_id}")
    edge = await db.get(WorkspaceEdgeModel, edge_id)
    if edge is None:
        db.add(WorkspaceEdgeModel(
            id=edge_id,
            project_name=project_name,
            source_object_id=source_id,
            target_object_id=target_id,
            relation_type=relation_type,
            edge_family="provenance",
            created_by="research_specialist",
            metadata_json={"run_id": run_id},
        ))
    elif (
        edge.project_name != project_name
        or edge.source_object_id != source_id
        or edge.target_object_id != target_id
    ):
        raise ValueError("Research provenance identity is already bound to a different graph edge.")


async def persist_research_workspace_graph(
    db: AsyncSession,
    *,
    project_name: str | None,
    session_id: str,
    run_id: str,
    state: ResearchState,
    research_status: str,
) -> dict[str, list[str]]:
    """Persist non-rejected sources, grounded evidence, and supported claims idempotently.

    This function participates in the caller's transaction. IDs are stable for a
    child run so retries update the same workspace objects and provenance edges.
    """
    if not project_name:
        return {"source_ids": [], "evidence_ids": [], "claim_ids": []}

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
    validation = CitationValidator.validate_all(
        claims=state.claims,
        evidence_map=evidence,
        sources_map=sources,
        strict=False,
    )
    accepted_claims = [
        claim
        for claim in [
            *validation["verified_facts"],
            *validation["inferences"],
            *validation["hypotheses"],
        ]
        if claim.verification_status != "unsupported"
        and all(evidence_id in evidence for evidence_id in claim.evidence_ids)
    ]

    source_object_ids: dict[str, str] = {}
    for source_id, source in sources.items():
        object_id = _stable_id("source", run_id, source_id)
        source_object_ids[source_id] = object_id
        await _upsert_object(
            db,
            object_id=object_id,
            project_name=project_name,
            session_id=session_id,
            object_type="research_source",
            title=source.title or source.canonical_id,
            content=source.abstract or source.url or source.canonical_id,
            metadata={
                "run_id": run_id,
                "research_status": research_status,
                "source_id": source.source_id,
                "canonical_id": source.canonical_id,
                "url": source.url,
                "authors": source.authors,
                "year": source.year,
                "venue": source.venue,
                "source_status": source.status.value,
                "relevance_score": source.relevance_score,
            },
        )

    evidence_object_ids: dict[str, str] = {}
    for evidence_id, item in evidence.items():
        object_id = _stable_id("evidence", run_id, evidence_id)
        evidence_object_ids[evidence_id] = object_id
        await _upsert_object(
            db,
            object_id=object_id,
            project_name=project_name,
            session_id=session_id,
            object_type="research_evidence",
            title=f"{item.source_title} · {item.source_locator}",
            content=item.extracted_text,
            metadata={
                "run_id": run_id,
                "research_status": research_status,
                "evidence_id": item.evidence_id,
                "source_id": item.source_id,
                "source_locator": item.source_locator,
                "confidence": item.confidence,
                "summary": item.summary,
            },
        )
        await _upsert_provenance_edge(
            db,
            run_id=run_id,
            project_name=project_name,
            source_id=source_object_ids[item.source_id],
            target_id=object_id,
            relation_type="contains_evidence",
        )

    claim_object_ids: dict[str, str] = {}
    for claim in accepted_claims:
        object_id = _stable_id("claim", run_id, claim.claim_id)
        claim_object_ids[claim.claim_id] = object_id
        await _upsert_object(
            db,
            object_id=object_id,
            project_name=project_name,
            session_id=session_id,
            object_type="research_claim",
            title=claim.claim_text,
            content=claim.claim_text,
            metadata={
                "run_id": run_id,
                "research_status": research_status,
                "claim_id": claim.claim_id,
                "claim_type": claim.claim_type.value,
                "verification_status": claim.verification_status,
                "evidence_ids": claim.evidence_ids,
                "notes": claim.notes,
            },
        )
        for evidence_id in claim.evidence_ids:
            await _upsert_provenance_edge(
                db,
                run_id=run_id,
                project_name=project_name,
                source_id=evidence_object_ids[evidence_id],
                target_id=object_id,
                relation_type="supports_claim",
            )

    await db.flush()
    return {
        "source_ids": list(source_object_ids.values()),
        "evidence_ids": list(evidence_object_ids.values()),
        "claim_ids": list(claim_object_ids.values()),
    }
