"""Unit tests for vector-aware semantic memory stores and project scoping."""

import pytest
from app.db.models import MemoryModel
from app.memory.base import MemoryType
from app.memory.embeddings.mock_provider import MockEmbeddingProvider
from app.memory.stores.sqlite_store import SqliteSemanticStore


@pytest.mark.asyncio
async def test_semantic_memory_store_vector_search_and_scoping(test_db_session):
    """Verify nearest-neighbor search, thresholding, and project scoping without cross-project leakage."""
    store = SqliteSemanticStore(test_db_session)
    provider = MockEmbeddingProvider(dimension=1536)

    # 1. Embed and store memories across two different projects
    atlas_text = "Project Atlas uses Python 3.12 for its core backend service."
    mercury_text = "Project Mercury is written in Rust and targets WebAssembly."
    unrelated_text = "The quick brown fox jumps over the lazy dog."

    atlas_vec = await provider.embed_query(atlas_text)
    mercury_vec = await provider.embed_query(mercury_text)
    unrelated_vec = await provider.embed_query(unrelated_text)

    mem_atlas = MemoryModel(
        memory_type=MemoryType.SEMANTIC.value,
        content=atlas_text,
        embedding=atlas_vec,
        embedding_model=provider.model_name,
        embedding_dim=provider.dimension,
        project_name="Atlas",
        is_active=True,
    )
    mem_mercury = MemoryModel(
        memory_type=MemoryType.SEMANTIC.value,
        content=mercury_text,
        embedding=mercury_vec,
        embedding_model=provider.model_name,
        embedding_dim=provider.dimension,
        project_name="Mercury",
        is_active=True,
    )
    mem_unrelated = MemoryModel(
        memory_type=MemoryType.SEMANTIC.value,
        content=unrelated_text,
        embedding=unrelated_vec,
        embedding_model=provider.model_name,
        embedding_dim=provider.dimension,
        project_name="General",
        is_active=True,
    )

    await store.store(mem_atlas)
    await store.store(mem_mercury)
    await store.store(mem_unrelated)

    # 2. Search querying for Python in Atlas: Atlas memory must be top match with high similarity
    query_vec = await provider.embed_query(atlas_text)
    results = await store.search(
        query_vector=query_vec,
        limit=5,
        min_similarity=0.5,
        project_name="Atlas",
    )
    assert len(results) == 1
    matched_mem, sim = results[0]
    assert matched_mem.id == mem_atlas.id
    assert matched_mem.project_name == "Atlas"
    assert sim >= 0.99  # Identical text produces exact match

    # 3. Project Isolation: Searching with project_name="Mercury" must NEVER leak Atlas memories
    mercury_results = await store.search(
        query_vector=query_vec,
        limit=5,
        min_similarity=0.0,
        project_name="Mercury",
    )
    assert all(m[0].project_name == "Mercury" for m in mercury_results)
    assert not any(m[0].id == mem_atlas.id for m in mercury_results)


@pytest.mark.asyncio
async def test_semantic_memory_supersede_and_archive(test_db_session):
    """Verify that superseding an old memory deactivates it and links to the new active memory."""
    store = SqliteSemanticStore(test_db_session)
    provider = MockEmbeddingProvider(dimension=1536)

    # 1. Store old memory
    old_text = "Project Atlas uses Python 3.11"
    old_vec = await provider.embed_query(old_text)
    old_mem = MemoryModel(
        memory_type=MemoryType.PROJECT.value,
        content=old_text,
        embedding=old_vec,
        project_name="Atlas",
        is_active=True,
    )
    await store.store(old_mem)

    # 2. Store new memory upgrading Python to 3.12
    new_text = "Project Atlas uses Python 3.12"
    new_vec = await provider.embed_query(new_text)
    new_mem = MemoryModel(
        memory_type=MemoryType.PROJECT.value,
        content=new_text,
        embedding=new_vec,
        project_name="Atlas",
        is_active=True,
    )
    await store.store(new_mem)

    # 3. Supersede old with new
    await store.supersede(old_mem.id, new_mem.id)

    # Verify old memory is now inactive and linked
    reloaded_old = await store.get_by_id(old_mem.id)
    reloaded_new = await store.get_by_id(new_mem.id)
    assert reloaded_old.is_active is False
    assert reloaded_old.superseded_by_id == new_mem.id
    assert reloaded_new.supersedes_id == old_mem.id

    # Search with is_active_only=True querying old_vec must NOT return old_mem even though it matches old_vec exactly
    old_search = await store.search(
        query_vector=old_vec,
        limit=5,
        min_similarity=-1.0,
        project_name="Atlas",
        is_active_only=True,
    )
    assert not any(m[0].id == old_mem.id for m in old_search)
    assert any(m[0].id == new_mem.id for m in old_search)

    # Searching with new_vec returns new_mem with similarity 1.0
    new_search = await store.search(
        query_vector=new_vec,
        limit=5,
        min_similarity=0.9,
        project_name="Atlas",
        is_active_only=True,
    )
    assert len(new_search) == 1
    assert new_search[0][0].id == new_mem.id

