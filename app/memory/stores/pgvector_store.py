"""PostgreSQL + pgvector implementation of SemanticMemoryStore."""

from typing import List, Optional, Tuple
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import MemoryModel
from app.memory.stores.base import SemanticMemoryStore


class PgVectorSemanticStore(SemanticMemoryStore):
    """
    Production-grade vector memory store utilizing native PostgreSQL pgvector extension
    with HNSW/IVFFlat index acceleration.
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
        # Cosine distance operator (<=>) via pgvector.sqlalchemy
        # distance in [0, 2], cosine_similarity = 1.0 - distance
        cos_dist = MemoryModel.embedding.cosine_distance(query_vector)
        similarity_expr = (1.0 - cos_dist).label("similarity")

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

        stmt = (
            select(MemoryModel, similarity_expr)
            .where(and_(*conditions))
            .order_by(cos_dist.asc())
            .limit(limit)
        )

        result = await self.db.execute(stmt)
        matches: List[Tuple[MemoryModel, float]] = []

        for row in result.all():
            mem, sim = row[0], float(row[1])
            if sim >= min_similarity:
                matches.append((mem, sim))

        return matches

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
