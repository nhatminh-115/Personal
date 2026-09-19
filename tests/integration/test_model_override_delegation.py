"""Integration tests for model override propagation into delegated specialists and inspector endpoints."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.api.server import create_app
from app.db.models import DelegationModel, MemoryModel, RunModel, SessionModel
from app.models.router import model_router
from app.models.routing_policy import ProviderMetadata
from app.orchestrator.graph import get_compiled_graph, set_global_checkpointer
from langgraph.checkpoint.memory import MemorySaver


@pytest.mark.asyncio
async def test_sessions_list_endpoint(test_db_session: AsyncSession):
    """GET /v1/sessions returns list of existing sessions ordered by updated_at."""
    s1 = SessionModel(id="sess-list-1", title="Session One")
    s2 = SessionModel(id="sess-list-2", title="Session Two")
    test_db_session.add(s1)
    test_db_session.add(s2)
    await test_db_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: test_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        session_ids = [s["id"] for s in data]
        assert "sess-list-1" in session_ids
        assert "sess-list-2" in session_ids

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_memory_inspector_endpoint(test_db_session: AsyncSession):
    """GET /v1/memory returns stored project memories with claim and evidence lineage."""
    mem = MemoryModel(
        session_id="sess-mem-1",
        memory_type="semantic",
        project_name="Stateful_LLM",
        key="finding_key_1",
        content="Stateful LLM architecture eliminates quadratic KV cache expansion.",
        confidence=0.95,
        metadata_json={
            "claim_ids": ["cl_01"],
            "evidence_ids": ["ev_01"],
            "sources_cited": ["arxiv:2312.00752"],
        },
    )
    test_db_session.add(mem)
    await test_db_session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = lambda: test_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Filtered by project_name
        resp = await client.get("/v1/memory?project_name=Stateful_LLM")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["key"] == "finding_key_1"
        assert data[0]["content"].startswith("Stateful LLM")
        assert data[0]["metadata_json"]["claim_ids"] == ["cl_01"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_research_inspector_endpoint(test_db_session: AsyncSession):
    """GET /v1/runs/{run_id}/research returns structured ResearchState from child specialist run."""
    # Seed parent run, child run, and delegation
    parent = RunModel(id="run-parent-res-1", session_id="sess-res-1", status="completed", user_message="Research topic")
    child = RunModel(id="run-child-res-1", session_id="sess-res-1", parent_run_id=parent.id, status="completed", user_message="Conduct research")
    delegation = DelegationModel(
        parent_run_id=parent.id,
        child_run_id=child.id,
        specialist_name="research",
        status="completed",
        result_summary="Research completed with 1 finding.",
    )
    test_db_session.add(parent)
    test_db_session.add(child)
    test_db_session.add(delegation)
    await test_db_session.commit()

    # Seed research state into LangGraph MemorySaver
    cp = MemorySaver()
    set_global_checkpointer(cp)

    fake_r_state = {
        "goal": {"user_query": "Investigate stateful architectures"},
        "queries": [{"query_text": "selective state spaces", "results_count": 5}],
        "sources": {
            "s1": {"canonical_id": "arxiv:2312.00752", "title": "Mamba", "status": "inspected"}
        },
        "inspected_source_ids": ["s1"],
        "evidence": {
            "ev1": {"extracted_text": "Selective SSM parameters", "confidence": 0.99}
        },
        "claims": [
            {"claim_id": "cl1", "claim_text": "Mamba replaces quadratic attention", "claim_type": "source_supported_fact"}
        ],
        "status": "completed",
    }

    from unittest.mock import patch
    mock_snapshot = MagicMock()
    mock_snapshot.values = {"research_state": fake_r_state}
    mock_graph = MagicMock()
    mock_graph.aget_state = AsyncMock(return_value=mock_snapshot)

    with patch("app.api.routes.runs.get_compiled_graph", new_callable=AsyncMock, return_value=mock_graph):
        app = create_app()
        app.dependency_overrides[get_db] = lambda: test_db_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Requesting via parent run_id inspects the child specialist research state
            resp = await client.get(f"/v1/runs/{parent.id}/research")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == parent.id
        assert data["child_run_id"] == child.id
        assert data["status"] == "completed"
        assert len(data["queries"]) == 1
        assert len(data["sources"]) == 1
        assert data["sources"][0]["canonical_id"] == "arxiv:2312.00752"
        assert len(data["evidence"]) == 1
        assert len(data["claims"]) == 1
        assert data["claims"][0]["claim_id"] == "cl1"

    app.dependency_overrides.clear()
