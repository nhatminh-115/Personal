"""Preflight unit test for the live dogfood audit helper.

Verifies that audit_dogfood_run executes without AttributeError against seeded
RunModel, DelegationModel, RunEventModel (using created_at and payload),
ResearchState snapshot, and MemoryModel records.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DelegationModel, MemoryModel, RunEventModel, RunModel, SessionModel
from app.research.models import ClaimType, EvidenceItem, ResearchClaim, ResearchQuery, ResearchSource, ResearchState, SourceStatus
from scripts.dogfood_research_live import audit_dogfood_run


@pytest.mark.asyncio
async def test_dogfood_audit_preflight(test_db_session: AsyncSession):
    # 1. Seed SessionModel
    session = SessionModel(id="sess-preflight-audit-1", title="Preflight Audit Session")
    test_db_session.add(session)
    await test_db_session.commit()

    # 2. Seed Parent and Child RunModel
    parent_run = RunModel(
        id="run-parent-audit-100",
        session_id=session.id,
        status="completed",
        user_message="Investigate stateful LLMs",
        final_response="Orchestrator synthesis",
    )
    test_db_session.add(parent_run)
    await test_db_session.commit()

    child_run = RunModel(
        id="run-child-audit-200",
        session_id=session.id,
        parent_run_id=parent_run.id,
        status="completed",
        user_message="Conduct scholarly research",
        final_response="Specialist synthesis",
    )
    test_db_session.add(child_run)
    await test_db_session.commit()

    # 3. Seed DelegationModel
    delegation = DelegationModel(
        parent_run_id=parent_run.id,
        parent_tool_call_id="call_deleg_01",
        child_run_id=child_run.id,
        specialist_name="research",
        status="completed",
        result_summary="[RESEARCH SPECIALIST - VALIDATED SYNTHESIS]\nResearch Status: completed\nSummary of findings.",
    )
    test_db_session.add(delegation)
    await test_db_session.commit()

    # 4. Seed RunEventModel records (using created_at and payload fields strictly)
    # Root event
    ev_root = RunEventModel(
        run_id=parent_run.id,
        event_type="tool_executed",
        payload={"tool": "delegate_task", "arguments": {"specialist_name": "research"}},
    )
    test_db_session.add(ev_root)

    # Child model_called event
    ev_model = RunEventModel(
        run_id=child_run.id,
        event_type="model_called",
        payload={
            "routing_decision": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "reason": "specialist_baseline",
            }
        },
    )
    test_db_session.add(ev_model)

    # Child tool_executed events
    tool_names = [
        "research_search",
        "read_document_section",
        "extract_evidence",
        "record_research_claim",
        "save_research_finding",
    ]
    for idx, t_name in enumerate(tool_names):
        ev_tool = RunEventModel(
            run_id=child_run.id,
            event_type="tool_executed",
            payload={"tool": t_name, "tool_call_id": f"call_{idx}"},
        )
        test_db_session.add(ev_tool)

    # 5. Seed MemoryModel for Stateful_LLM_Architecture
    mem = MemoryModel(
        session_id=session.id,
        memory_type="semantic",
        project_name="Stateful_LLM_Architecture",
        key="research_finding_cl_01",
        content="Stateful LLM maintaining compact recurrent state during inference.",
        metadata_json={
            "claim_ids": ["cl_01"],
            "evidence_ids": ["ev_01"],
            "sources_cited": ["arxiv:2312.00752"],
        },
    )
    test_db_session.add(mem)
    await test_db_session.commit()

    # 6. Mock LangGraph checkpointed ResearchState
    r_state = ResearchState()
    r_state.queries.append(
        ResearchQuery(
            query_id="q1",
            query_text="selective state spaces linear attention",
            search_type="broad",
            results_count=3,
        )
    )
    r_state.sources["arxiv_2312_00752"] = ResearchSource(
        source_id="arxiv_2312_00752",
        canonical_id="arxiv:2312.00752",
        title="Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
        authors=["Albert Gu", "Tri Dao"],
        year=2023,
        status=SourceStatus.INSPECTED,
        metadata={"providers": ["semantic_scholar", "arxiv"], "full_text_status": "available"},
    )
    r_state.inspected_source_ids.append("arxiv_2312_00752")
    r_state.evidence["ev_01"] = EvidenceItem(
        evidence_id="ev_01",
        source_id="arxiv_2312_00752",
        source_title="Mamba",
        source_locator="Section: methods",
        extracted_text="Selective SSM parameterizes transitions as input-dependent.",
        confidence=0.98,
    )
    r_state.claims.append(
        ResearchClaim(
            claim_id="cl_01",
            claim_text="Mamba maintains input-dependent state during inference.",
            claim_type=ClaimType.SOURCE_SUPPORTED_FACT,
            evidence_ids=["ev_01"],
        )
    )

    mock_snapshot = MagicMock()
    mock_snapshot.values = {"research_state": r_state.to_dict()}

    mock_graph = MagicMock()
    mock_graph.aget_state = AsyncMock(return_value=mock_snapshot)

    # 7. Execute audit_dogfood_run
    report = await audit_dogfood_run(
        parent_run_id=parent_run.id,
        db=test_db_session,
        graph=mock_graph,
        elapsed_seconds=1.23,
    )

    # 8. Assertions: ensure no AttributeError and all extracted values match
    assert report["parent_run_id"] == "run-parent-audit-100"
    assert report["child_run_id"] == "run-child-audit-200"
    assert report["specialist_name"] == "research"
    assert report["actual_model_provider"] == "openai"
    assert report["actual_model_name"] == "gpt-4o-mini"
    assert report["model_call_count"] == 1
    assert report["tool_sequence"] == tool_names
    assert report["child_run_status"] == "completed"
    assert report["delegation_status"] == "completed"
    assert report["parsed_synthesis_status"] == "completed"
    assert report["queries_count"] == 1
    assert report["sources_count"] == 1
    assert report["inspected_count"] == 1
    assert report["evidence_count"] == 1
    assert report["claims_count"] == 1
    assert report["memory_count"] == 1
