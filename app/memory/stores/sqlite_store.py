"""SQLite test/dev fallback implementation of SemanticMemoryStore with in-memory cosine similarity."""

import math
from typing import List, Optional, Tuple
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import MemoryModel
from app.memory.stores.base import SemanticMemoryStore


def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute exact cosine similarity between two float vectors."""
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


class SqliteSemanticStore(SemanticMemoryStore):
    """
    Lightweight development and test store for SQLite environments.
    Stores vectors via SQLAlchemy Vector column type and computes exact cosine
    similarity in Python without requiring a PostgreSQL pgvector daemon.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store(self, memory: MemoryModel) -> MemoryModel:
        self.db.add(memory)
        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    async def search(
        self,
        query_vector: List[float],
        limit: int = 5,
        min_similarity: float = 0.0,
        project_name: Optional[str] = None,
        memory_types: Optional[List[str]] = None,
        is_active_only: bool = True,
        embedding_model: Optional[str] = None,
        embedding_dim: Optional[int] = None,
        exact_project_only: bool = False,
        allow_any_project: bool = False,
    ) -> List[Tuple[MemoryModel, float]]:
        conditions = [MemoryModel.embedding.isnot(None)]

        if is_active_only:
            conditions.append(MemoryModel.is_active.is_(True))

        if not allow_any_project:
            if project_name is not None:
                if exact_project_only:
                    conditions.append(MemoryModel.project_name == project_name)
                else:
                    conditions.append(
                        or_(MemoryModel.project_name == project_name, MemoryModel.project_name.is_(None))
                    )
            else:
                conditions.append(MemoryModel.project_name.is_(None))

        if memory_types:
            conditions.append(MemoryModel.memory_type.in_(memory_types))

        if embedding_model is not None:
            conditions.append(MemoryModel.embedding_model == embedding_model)

        if embedding_dim is not None:
            conditions.append(MemoryModel.embedding_dim == embedding_dim)

        stmt = select(MemoryModel).where(and_(*conditions))
        result = await self.db.execute(stmt)
        memories = list(result.scalars().all())

        scored_matches: List[Tuple[MemoryModel, float]] = []
        for mem in memories:
            if mem.embedding is not None:
                if embedding_model is not None and mem.embedding_model != embedding_model:
                    continue
                if embedding_dim is not None and mem.embedding_dim != embedding_dim:
                    continue
                sim = _cosine_similarity(query_vector, list(mem.embedding))
                if sim >= min_similarity:
                    scored_matches.append((mem, round(sim, 6)))

        # Sort descending by similarity score
        scored_matches.sort(key=lambda x: x[1], reverse=True)
        return scored_matches[:limit]

    async def get_by_id(self, memory_id: str) -> Optional[MemoryModel]:
        stmt = select(MemoryModel).where(MemoryModel.id == memory_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def supersede(self, old_memory_id: str, new_memory_id: str) -> None:
        old_mem = await self.get_by_id(old_memory_id)
        new_mem = await self.get_by_id(new_memory_id)
        if old_mem and new_mem:
            old_mem.is_active = False
            old_mem.superseded_by_id = new_mem.id
            new_mem.supersedes_id = old_mem.id
            await self.db.commit()

    async def archive(self, memory_id: str) -> None:
        mem = await self.get_by_id(memory_id)
        if mem:
            mem.is_active = False
            await self.db.commit()

    async def delete(self, memory_id: str) -> None:
        mem = await self.get_by_id(memory_id)
        if mem:
            await self.db.delete(mem)
            await self.db.commit()
