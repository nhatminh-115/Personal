"""SQLAlchemy-backed implementation of the MemoryService."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import MemoryModel, MessageModel, SessionModel
from app.memory.base import MemoryService, MemoryType
from app.memory.embeddings.router import EmbeddingRouter, embedding_router
from app.memory.stores.factory import get_semantic_store


class SQLMemoryService(MemoryService):
    """Production memory service persisting to database via SQLAlchemy and vector store."""

    def __init__(
        self,
        db: AsyncSession,
        router: Optional[EmbeddingRouter] = None,
    ) -> None:
        self.db = db
        self.embedding_router = router or embedding_router
        self.store = get_semantic_store(db)

    # --- Working Memory ---
    async def get_or_create_session(self, session_id: str, title: Optional[str] = None) -> SessionModel:
        query = select(SessionModel).where(SessionModel.id == session_id)
        result = await self.db.execute(query)
        session = result.scalar_one_or_none()

        if session is None:
            session = SessionModel(
                id=session_id,
                title=title or f"Session {session_id[:8]}",
                metadata_json={},
            )
            self.db.add(session)
            await self.db.commit()
            await self.db.refresh(session)
            logger.info(f"Initialized new session '{session_id}'", extra={"session_id": session_id})
        return session

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: Optional[int] = None,
    ) -> MessageModel:
        # Ensure session exists first
        await self.get_or_create_session(session_id)

        msg = MessageModel(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def get_session_messages(self, session_id: str, limit: int = 50) -> List[MessageModel]:
        query = (
            select(MessageModel)
            .where(MessageModel.session_id == session_id)
            .order_by(MessageModel.created_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # --- Episodic Memory ---
    async def record_episodic_memory(
        self,
        session_id: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryModel:
        memory = MemoryModel(
            session_id=session_id,
            memory_type=MemoryType.EPISODIC.value,
            content=summary,
            metadata_json=metadata or {},
        )
        self.db.add(memory)
        await self.db.commit()
        await self.db.refresh(memory)
        logger.info(f"Recorded episodic memory for session {session_id}", extra={"session_id": session_id})
        return memory

    async def get_recent_episodes(self, session_id: Optional[str] = None, limit: int = 5) -> List[MemoryModel]:
        query = select(MemoryModel).where(MemoryModel.memory_type == MemoryType.EPISODIC.value)
        if session_id:
            query = query.where(MemoryModel.session_id == session_id)
        query = query.order_by(MemoryModel.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # --- Semantic Memory ---
    async def store_semantic_memory(
        self,
        content: str,
        embedding: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        project_name: Optional[str] = None,
    ) -> MemoryModel:
        vec = embedding
        if vec is None:
            vec = await self.embedding_router.embed_query(content)

        memory = MemoryModel(
            session_id=None,
            memory_type=MemoryType.SEMANTIC.value,
            content=content,
            embedding=vec,
            embedding_model=self.embedding_router.current_model_name,
            embedding_dim=len(vec),
            project_name=project_name,
            is_active=True,
            metadata_json=metadata or {},
        )
        return await self.store.store(memory)

    async def search_semantic_memory(
        self,
        query: str,
        embedding: Optional[List[float]] = None,
        limit: int = 5,
        min_similarity: float = 0.0,
        project_name: Optional[str] = None,
        is_active_only: bool = True,
    ) -> List[MemoryModel]:
        query_vec = embedding
        if query_vec is None:
            query_vec = await self.embedding_router.embed_query(query)

        matches = await self.store.search(
            query_vector=query_vec,
            limit=limit,
            min_similarity=min_similarity,
            project_name=project_name,
            memory_types=[MemoryType.SEMANTIC.value],
            is_active_only=is_active_only,
        )
        return [m[0] for m in matches]

    # --- Memory Lifecycle & Superseding ---
    async def supersede_memory(self, old_memory_id: str, new_memory_id: str) -> None:
        await self.store.supersede(old_memory_id, new_memory_id)

    async def archive_memory(self, memory_id: str) -> None:
        await self.store.archive(memory_id)

    # --- Profile Memory ---
    async def set_profile_fact(self, key: str, value: str, metadata: Optional[Dict[str, Any]] = None) -> MemoryModel:
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROFILE.value,
            MemoryModel.key == key,
        )
        result = await self.db.execute(query)
        memory = result.scalar_one_or_none()

        if memory:
            memory.content = value
            memory.metadata_json = metadata or memory.metadata_json
            memory.is_active = True
        else:
            memory = MemoryModel(
                session_id=None,
                memory_type=MemoryType.PROFILE.value,
                key=key,
                content=value,
                is_active=True,
                metadata_json=metadata or {},
            )
            self.db.add(memory)

        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    async def get_profile_fact(self, key: str) -> Optional[str]:
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROFILE.value,
            MemoryModel.key == key,
            MemoryModel.is_active.is_(True),
        )
        result = await self.db.execute(query)
        memory = result.scalar_one_or_none()
        return memory.content if memory else None

    async def get_all_profile_facts(self) -> Dict[str, str]:
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROFILE.value,
            MemoryModel.is_active.is_(True),
        )
        result = await self.db.execute(query)
        memories = result.scalars().all()
        return {m.key: m.content for m in memories if m.key}

    # --- Project Memory ---
    async def store_project_memory(
        self,
        project_name: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> MemoryModel:
        full_metadata = metadata or {}
        full_metadata["project_name"] = project_name

        vec = embedding
        if vec is None:
            vec = await self.embedding_router.embed_query(content)

        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROJECT.value,
            MemoryModel.key == f"{project_name}:{key}",
        )
        result = await self.db.execute(query)
        memory = result.scalar_one_or_none()

        if memory:
            memory.content = content
            memory.embedding = vec
            memory.embedding_model = self.embedding_router.current_model_name
            memory.embedding_dim = len(vec)
            memory.project_name = project_name
            memory.metadata_json = full_metadata
            memory.is_active = True
        else:
            memory = MemoryModel(
                session_id=None,
                memory_type=MemoryType.PROJECT.value,
                key=f"{project_name}:{key}",
                content=content,
                embedding=vec,
                embedding_model=self.embedding_router.current_model_name,
                embedding_dim=len(vec),
                project_name=project_name,
                is_active=True,
                metadata_json=full_metadata,
            )
            self.db.add(memory)

        await self.db.commit()
        await self.db.refresh(memory)
        return memory

    async def get_project_memories(self, project_name: str, is_active_only: bool = True) -> List[MemoryModel]:
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROJECT.value,
            MemoryModel.key.like(f"{project_name}:%"),
        )
        if is_active_only:
            query = query.where(MemoryModel.is_active.is_(True))
        result = await self.db.execute(query)
        return list(result.scalars().all())

