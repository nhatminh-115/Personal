"""Unit tests for Milestone 2B Context Assembler and Memory Candidate Pipeline."""

import pytest
from app.db.models import MemoryModel
from app.memory.base import MemoryType
from app.memory.context import AssembledContext, ContextAssembler
from app.memory.embeddings.mock_provider import MockEmbeddingProvider
from app.memory.embeddings.router import EmbeddingRouter
from app.memory.pipeline import MemoryCandidate, MemoryCandidatePipeline
from app.memory.service import SQLMemoryService
from app.memory.stores.factory import create_semantic_store


@pytest.fixture
def mock_router():
    return EmbeddingRouter(providers={"mock": MockEmbeddingProvider(dimension=1536)}, default_provider="mock")


@pytest.mark.asyncio
async def test_memory_candidate_pipeline_conservative_extraction():
    """Verify conservative extraction: ignores casual chat, captures explicit directives and project facts."""
    pipeline = MemoryCandidatePipeline()

    # 1. Casual chat -> No candidates
    cands = pipeline.extract_candidates("Hello there, how are you doing today?")
    assert len(cands) == 0

    cands_bye = pipeline.extract_candidates("Thanks for your help! Goodbye.")
    assert len(cands_bye) == 0

    # 2. Explicit project directive
    cands_proj = pipeline.extract_candidates("Please remember that Project Atlas uses Python 3.12")
    assert len(cands_proj) == 1
    assert cands_proj[0].memory_type == MemoryType.PROJECT
    assert cands_proj[0].project_name == "Atlas"
    assert cands_proj[0].key == "python_version"
    assert "Python 3.12" in cands_proj[0].content

    # 3. Direct project statement
    cands_proj2 = pipeline.extract_candidates("Project Titan targets PostgreSQL 16")
    assert len(cands_proj2) == 1
    assert cands_proj2[0].memory_type == MemoryType.PROJECT
    assert cands_proj2[0].project_name == "Titan"
    assert "PostgreSQL 16" in cands_proj2[0].content

    # 4. Explicit profile preference
    cands_pref = pipeline.extract_candidates("Please note that I prefer dark mode theme")
    assert len(cands_pref) == 1
    assert cands_pref[0].memory_type == MemoryType.PROFILE
    assert "dark mode" in cands_pref[0].content

    # 5. Generic explicit directive -> Semantic
    cands_sem = pipeline.extract_candidates("Remember that the production API gateway URL is https://api.prod.aura")
    assert len(cands_sem) == 1
    assert cands_sem[0].memory_type == MemoryType.SEMANTIC
    assert "api.prod.aura" in cands_sem[0].content


@pytest.mark.asyncio
async def test_memory_candidate_pipeline_superseding_lineage(test_db_session, mock_router):
    """Verify that updating a project fact supersedes previous active fact with full lineage audit trail."""
    service = SQLMemoryService(db=test_db_session, router=mock_router)
    pipeline = MemoryCandidatePipeline()

    # Turn 1: Project Atlas uses Python 3.12
    cands1 = pipeline.extract_candidates("Project Atlas uses Python 3.12")
    saved1 = await pipeline.process_and_commit(
        candidates=cands1,
        session_id="session-audit-1",
        run_id="run-1",
        memory_service=service,
    )
    assert len(saved1) == 1
    mem1_id = saved1[0].id
    assert saved1[0].is_active is True
    assert saved1[0].supersedes_id is None

    # Turn 2: Project Atlas upgraded to Python 3.13
    cands2 = pipeline.extract_candidates("Project Atlas upgraded to Python 3.13")
    saved2 = await pipeline.process_and_commit(
        candidates=cands2,
        session_id="session-audit-2",
        run_id="run-2",
        memory_service=service,
    )
    assert len(saved2) == 1
    mem2 = saved2[0]
    assert mem2.is_active is True
    assert mem2.supersedes_id == mem1_id
    assert "Python 3.13" in mem2.content

    # Verify old row was deactivated and linked to new row
    old_row = await test_db_session.get(MemoryModel, mem1_id)
    assert old_row.is_active is False
    assert old_row.superseded_by_id == mem2.id

    # Active query should only return the new memory
    active_mems = await service.get_project_memories("Atlas", is_active_only=True)
    assert len(active_mems) == 1
    assert active_mems[0].id == mem2.id
    assert "Python 3.13" in active_mems[0].content


@pytest.mark.asyncio
async def test_context_assembler_multitier_and_scoping(test_db_session, mock_router):
    """Verify ContextAssembler synthesizes multi-tier context and respects project boundary scoping."""
    service = SQLMemoryService(db=test_db_session, router=mock_router)
    assembler = ContextAssembler(memory_service=service)

    # Seed profile memory
    await service.set_profile_fact("editor", "VS Code")
    await service.set_profile_fact("theme", "dracula")

    # Seed project memory for Atlas and Titan
    await service.store_project_memory("Atlas", "python_version", "Project Atlas uses Python 3.12")
    await service.store_project_memory("Titan", "python_version", "Project Titan uses Python 3.11")

    # Seed episodic memory
    await service.record_episodic_memory("sess-test", "Configured testing environment for project Atlas")

    # Assemble for project Atlas
    ctx_atlas = await assembler.assemble_context(
        session_id="sess-test",
        user_message="How do I run tests for Atlas?",
        project_name="Atlas",
    )

    # Check profile facts
    assert ctx_atlas.profile_facts.get("editor") == "VS Code"
    assert ctx_atlas.profile_facts.get("theme") == "dracula"

    # Check project scoping: Atlas should be present, Titan should be excluded
    assert any("Python 3.12" in f for f in ctx_atlas.project_facts)
    assert not any("Python 3.11" in f for f in ctx_atlas.project_facts)

    # Check formatting for system prompt
    formatted = ctx_atlas.format_for_system_prompt()
    assert "### User Profile & Preferences:" in formatted
    assert "### Project Knowledge (Atlas):" in formatted
    assert "Project Atlas uses Python 3.12" in formatted
    assert "Python 3.11" not in formatted
