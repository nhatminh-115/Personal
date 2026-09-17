"""Real integration tests for PostgreSQL + pgvector extension, catalog schema, and vector queries."""

import os
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import MemoryModel
from app.memory.base import MemoryType
from app.memory.stores.pgvector_store import PgVectorSemanticStore


POSTGRES_TEST_URL = os.environ.get("AURA_POSTGRES_TEST_URL") or os.environ.get("POSTGRES_TEST_URL")


@pytest.fixture
async def pg_session():
    """Fixture providing real PostgreSQL async session if AURA_POSTGRES_TEST_URL is configured."""
    if not POSTGRES_TEST_URL:
        pytest.skip("PostgreSQL test instance not configured. Set AURA_POSTGRES_TEST_URL to execute.")

    engine = create_async_engine(POSTGRES_TEST_URL, future=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"Cannot connect to PostgreSQL at {POSTGRES_TEST_URL}: {e}")

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_pgvector_catalog_and_schema_inspection(pg_session):
    """
    Verify through SQL/catalog inspection:
    - Extension 'vector' exists
    - Column 'memories.embedding' is actual native vector(1536)
    - HNSW cosine index 'ix_memories_embedding_hnsw' exists with vector_cosine_ops
    """
    # 1. Inspect pg_extension
    res_ext = await pg_session.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
    ext_row = res_ext.scalar_one_or_none()
    assert ext_row == "vector", "PostgreSQL extension 'vector' is not installed in database!"

    # 2. Inspect information_schema.columns for memories.embedding
    res_col = await pg_session.execute(
        text(
            """
            SELECT udt_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'memories' AND column_name = 'embedding'
            """
        )
    )
    col_row = res_col.fetchone()
    assert col_row is not None, "Column 'memories.embedding' not found in information_schema!"
    udt_name, data_type = col_row
    assert udt_name == "vector", f"Expected udt_name 'vector', got '{udt_name}' ({data_type})"

    # 3. Inspect pg_indexes for HNSW index
    res_idx = await pg_session.execute(
        text(
            """
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'memories' AND indexname = 'ix_memories_embedding_hnsw'
            """
        )
    )
    idx_row = res_idx.fetchone()
    assert idx_row is not None, "HNSW index 'ix_memories_embedding_hnsw' not found in pg_indexes!"
    indexname, indexdef = idx_row
    assert "hnsw" in indexdef.lower(), f"Index does not use HNSW algorithm: {indexdef}"
    assert "vector_cosine_ops" in indexdef.lower(), f"Index does not use vector_cosine_ops: {indexdef}"


@pytest.mark.asyncio
async def test_postgres_pgvector_insert_and_cosine_search(pg_session):
    """Verify real vector insertion and cosine nearest-neighbor query (<=>) via PgVectorSemanticStore."""
    store = PgVectorSemanticStore(pg_session)

    # 1536-dim unit vectors
    vec_a = [0.0] * 1536
    vec_a[0] = 1.0  # Vector A along dim 0

    vec_b = [0.0] * 1536
    vec_b[1] = 1.0  # Vector B along dim 1 (orthogonal)

    # Store memory for Project Atlas
    mem_atlas = MemoryModel(
        memory_type=MemoryType.PROJECT.value,
        key="Atlas:python",
        content="Project Atlas runs Python 3.12",
        embedding=vec_a,
        embedding_model="mock-embedding-v1",
        embedding_dim=1536,
        project_name="Atlas",
        is_active=True,
    )
    await store.store(mem_atlas)

    # Store memory for Project Titan
    mem_titan = MemoryModel(
        memory_type=MemoryType.PROJECT.value,
        key="Titan:python",
        content="Project Titan runs Python 3.11",
        embedding=vec_b,
        embedding_model="mock-embedding-v1",
        embedding_dim=1536,
        project_name="Titan",
        is_active=True,
    )
    await store.store(mem_titan)

    # Search with query aligned with vec_a
    results = await store.search(
        query_vector=vec_a,
        limit=5,
        min_similarity=0.5,
        project_name="Atlas",
        embedding_model="mock-embedding-v1",
        embedding_dim=1536,
    )
    assert len(results) == 1
    matched_mem, sim = results[0]
    assert matched_mem.id == mem_atlas.id
    assert sim > 0.99
    assert matched_mem.project_name == "Atlas"
