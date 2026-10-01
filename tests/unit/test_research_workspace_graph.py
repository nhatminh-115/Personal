"""Research artifacts persist as scoped, idempotent workspace graph objects."""

import pytest
from sqlalchemy import select

from app.db.models import WorkspaceEdgeModel, WorkspaceObjectModel
from app.memory.context_compiler import WorkspaceContextCompiler
from app.research.models import (
    ClaimType,
    EvidenceItem,
    ResearchClaim,
    ResearchGoal,
    ResearchSource,
    ResearchState,
    SourceStatus,
)
from app.research.workspace import persist_research_workspace_graph


@pytest.mark.asyncio
async def test_research_graph_persists_only_supported_project_artifacts_idempotently(test_db_session):
    state = ResearchState(
        goal=ResearchGoal(goal_id="goal-1", user_query="Compare state models", project_name="project-a"),
        sources={
            "source-1": ResearchSource(
                source_id="source-1", canonical_id="doi:1", title="Prior paper",
                abstract="A paper about state representations.", status=SourceStatus.INSPECTED,
            ),
            "source-rejected": ResearchSource(
                source_id="source-rejected", canonical_id="doi:rejected", title="Rejected source",
                status=SourceStatus.REJECTED,
            ),
        },
        evidence={
            "evidence-1": EvidenceItem(
                evidence_id="evidence-1", source_id="source-1", source_title="Prior paper",
                source_locator="Methods", extracted_text="The method uses a fixed-size state.", confidence=0.92,
            ),
            "evidence-rejected": EvidenceItem(
                evidence_id="evidence-rejected", source_id="source-rejected", source_title="Rejected source",
                source_locator="Abstract", extracted_text="This evidence comes from a rejected source.",
            ),
        },
        claims=[
            ResearchClaim(
                claim_id="claim-verified", claim_text="The method uses a fixed-size state.",
                claim_type=ClaimType.SOURCE_SUPPORTED_FACT, evidence_ids=["evidence-1"],
            ),
            ResearchClaim(
                claim_id="claim-hypothesis", claim_text="This may reduce retrieval cost.",
                claim_type=ClaimType.HYPOTHESIS,
            ),
            ResearchClaim(
                claim_id="claim-unsupported", claim_text="The method is novel.",
                claim_type=ClaimType.SOURCE_SUPPORTED_FACT, evidence_ids=["missing-evidence"],
            ),
        ],
    )

    first = await persist_research_workspace_graph(
        test_db_session,
        project_name="project-a",
        session_id="session-a",
        run_id="run-a",
        state=state,
        research_status="insufficient_evidence",
    )
    await test_db_session.commit()

    objects = list((await test_db_session.execute(select(WorkspaceObjectModel))).scalars())
    edges = list((await test_db_session.execute(select(WorkspaceEdgeModel))).scalars())
    assert {item.object_type for item in objects} == {"research_source", "research_evidence", "research_claim"}
    assert len(objects) == 4
    assert len(edges) == 2
    assert all(item.project_name == "project-a" and item.session_id == "session-a" for item in objects)
    assert {item.metadata_json.get("claim_id") for item in objects if item.object_type == "research_claim"} == {
        "claim-verified", "claim-hypothesis",
    }
    assert all(item.edge_family == "provenance" for item in edges)

    claim_id = next(item.id for item in objects if item.metadata_json.get("claim_id") == "claim-verified")
    evidence_id = next(item.id for item in objects if item.metadata_json.get("evidence_id") == "evidence-1")
    source_id = next(item.id for item in objects if item.metadata_json.get("source_id") == "source-1")
    compiled = await WorkspaceContextCompiler(test_db_session).compile(
        "project-a", [claim_id, evidence_id, source_id]
    )
    assert "The method uses a fixed-size state." in compiled.prompt_text
    assert {item.object_type for item in compiled.objects} == {
        "research_source", "research_evidence", "research_claim",
    }

    second = await persist_research_workspace_graph(
        test_db_session,
        project_name="project-a",
        session_id="session-a",
        run_id="run-a",
        state=state,
        research_status="insufficient_evidence",
    )
    await test_db_session.commit()
    objects_after_retry = list((await test_db_session.execute(select(WorkspaceObjectModel))).scalars())
    edges_after_retry = list((await test_db_session.execute(select(WorkspaceEdgeModel))).scalars())
    assert first == second
    assert len(objects_after_retry) == len(objects)
    assert len(edges_after_retry) == len(edges)


@pytest.mark.asyncio
async def test_research_without_trusted_project_scope_is_not_promoted(test_db_session):
    result = await persist_research_workspace_graph(
        test_db_session,
        project_name=None,
        session_id="session-a",
        run_id="run-a",
        state=ResearchState(),
        research_status="insufficient_evidence",
    )
    assert result == {"source_ids": [], "evidence_ids": [], "claim_ids": []}
    assert list((await test_db_session.execute(select(WorkspaceObjectModel))).scalars()) == []
