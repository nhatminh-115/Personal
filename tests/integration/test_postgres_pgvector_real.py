"""Real integration tests for PostgreSQL + pgvector extension, catalog schema, and vector queries."""

import asyncio
import os
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func as sa_func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import MemoryModel, RunModel, SessionModel
from app.memory.base import MemoryType
from app.memory.service import SQLMemoryService
from app.api.routes.memory import _set_memory_active
from app.api.run_resume_lock import _postgres_run_resume_lock
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

    from app.db.models import generate_uuid, utc_now

    # Store memory for Project Atlas
    mem_atlas = MemoryModel(
        id=generate_uuid(),
        memory_type=MemoryType.PROJECT.value,
        key="Atlas:python",
        content="Project Atlas runs Python 3.12",
        embedding=vec_a,
        embedding_model="mock-embedding-v1",
        embedding_dim=1536,
        project_name="Atlas",
        is_active=True,
        metadata_json={},
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    await store.store(mem_atlas)

    # Store memory for Project Titan
    mem_titan = MemoryModel(
        id=generate_uuid(),
        memory_type=MemoryType.PROJECT.value,
        key="Titan:python",
        content="Project Titan runs Python 3.11",
        embedding=vec_b,
        embedding_model="mock-embedding-v1",
        embedding_dim=1536,
        project_name="Titan",
        is_active=True,
        metadata_json={},
        created_at=utc_now(),
        updated_at=utc_now(),
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


@pytest.mark.asyncio
async def test_postgres_concurrent_profile_writes_keep_one_active_version(pg_session):
    """Same-key profile writes serialize and retain the supersession chain."""
    key = f"concurrent-profile-{uuid.uuid4()}"
    engine = pg_session.bind
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def write_fact(value: str):
        async with session_factory() as session:
            return await SQLMemoryService(session).set_profile_fact(key, value)

    try:
        await asyncio.gather(write_fact("first value"), write_fact("second value"))
        async with session_factory() as session:
            rows = list((await session.execute(
                select(MemoryModel).where(
                    MemoryModel.memory_type == MemoryType.PROFILE.value,
                    MemoryModel.project_name.is_(None),
                    MemoryModel.key == key,
                ).order_by(MemoryModel.created_at, MemoryModel.id)
            )).scalars())
            active = [row for row in rows if row.is_active]
            inactive = [row for row in rows if not row.is_active]
            assert len(rows) == 2
            assert len(active) == 1
            assert len(inactive) == 1
            assert inactive[0].superseded_by_id == active[0].id
    finally:
        async with session_factory() as session:
            await session.execute(delete(MemoryModel).where(
                MemoryModel.memory_type == MemoryType.PROFILE.value,
                MemoryModel.project_name.is_(None),
                MemoryModel.key == key,
            ))
            await session.commit()


@pytest.mark.asyncio
async def test_postgres_concurrent_memory_restores_reject_second_active_version(pg_session):
    """Two archived versions restored simultaneously cannot both become active."""
    key = f"concurrent-restore-{uuid.uuid4()}"
    ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    engine = pg_session.bind
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        session.add_all([
            MemoryModel(
                id=memory_id,
                memory_type=MemoryType.PROFILE.value,
                project_name=None,
                key=key,
                content=f"archived-{index}",
                confidence=1.0,
                is_active=False,
                metadata_json={},
            )
            for index, memory_id in enumerate(ids)
        ])
        await session.commit()

    async def restore(memory_id: str):
        async with session_factory() as session:
            return await _set_memory_active(
                session,
                memory_id=memory_id,
                memory_type=MemoryType.PROFILE.value,
                project_name=None,
                not_found_detail="Profile memory not found.",
                is_active=True,
            )

    try:
        results = await asyncio.gather(restore(ids[0]), restore(ids[1]), return_exceptions=True)
        assert sum(not isinstance(result, Exception) for result in results) == 1
        conflicts = [result for result in results if isinstance(result, HTTPException)]
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409

        async with session_factory() as session:
            active_count = await session.scalar(
                select(sa_func.count()).select_from(MemoryModel).where(
                    MemoryModel.memory_type == MemoryType.PROFILE.value,
                    MemoryModel.project_name.is_(None),
                    MemoryModel.key == key,
                    MemoryModel.is_active.is_(True),
                )
            )
            assert active_count == 1
    finally:
        async with session_factory() as session:
            await session.execute(delete(MemoryModel).where(MemoryModel.id.in_(ids)))
            await session.commit()


@pytest.mark.asyncio
async def test_postgres_run_resume_lock_serializes_independent_engines(pg_session):
    """A second API worker cannot resume the same run while the first is active."""
    run_id = str(uuid.uuid4())
    first_engine = pg_session.bind
    second_engine = create_async_engine(POSTGRES_TEST_URL, future=True)
    first_acquired = asyncio.Event()
    second_attempting = asyncio.Event()
    release_first = asyncio.Event()
    second_acquired = asyncio.Event()

    async def hold_first_lock():
        async with _postgres_run_resume_lock(first_engine, run_id):
            first_acquired.set()
            await release_first.wait()

    async def acquire_second_lock():
        second_attempting.set()
        async with _postgres_run_resume_lock(second_engine, run_id):
            second_acquired.set()

    first_task = asyncio.create_task(hold_first_lock())
    second_task = None
    try:
        await asyncio.wait_for(first_acquired.wait(), timeout=5)
        second_task = asyncio.create_task(acquire_second_lock())
        await asyncio.wait_for(second_attempting.wait(), timeout=5)
        await asyncio.sleep(0.1)
        assert not second_acquired.is_set()

        release_first.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=5)
        assert second_acquired.is_set()
    finally:
        release_first.set()
        if not first_task.done():
            await first_task
        if second_task is not None and not second_task.done():
            await second_task
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_chat_turn_id_is_unique_within_a_session(pg_session):
    """Concurrent first deliveries for one client turn reserve only one run."""
    session_id = str(uuid.uuid4())
    client_turn_id = str(uuid.uuid4())
    engine = pg_session.bind
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        session.add(SessionModel(id=session_id, title="Idempotency integration"))
        await session.commit()

    async def reserve_run() -> bool:
        async with session_factory() as session:
            session.add(RunModel(
                id=str(uuid.uuid4()),
                session_id=session_id,
                client_turn_id=client_turn_id,
                request_fingerprint="a" * 64,
                status="running",
                user_message="same turn",
            ))
            try:
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
                return False

    try:
        assert sorted(await asyncio.gather(reserve_run(), reserve_run())) == [False, True]
        async with session_factory() as session:
            rows = await session.scalar(
                select(sa_func.count()).select_from(RunModel).where(
                    RunModel.session_id == session_id,
                    RunModel.client_turn_id == client_turn_id,
                )
            )
            assert rows == 1
    finally:
        async with session_factory() as session:
            await session.execute(delete(RunModel).where(RunModel.session_id == session_id))
            await session.execute(delete(SessionModel).where(SessionModel.id == session_id))
            await session.commit()


@pytest.mark.asyncio
async def test_postgres_concurrent_first_requests_reuse_one_session(pg_session):
    """Concurrent live-chat starts with one session ID converge on one row."""
    session_id = str(uuid.uuid4())
    engine = pg_session.bind
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def get_session():
        async with session_factory() as session:
            return await SQLMemoryService(session).get_or_create_session(session_id)

    try:
        sessions = await asyncio.gather(get_session(), get_session())
        assert {session.id for session in sessions} == {session_id}
        async with session_factory() as session:
            count = await session.scalar(
                select(sa_func.count()).select_from(SessionModel).where(SessionModel.id == session_id)
            )
            assert count == 1
    finally:
        async with session_factory() as session:
            await session.execute(delete(SessionModel).where(SessionModel.id == session_id))
            await session.commit()
