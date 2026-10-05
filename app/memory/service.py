"""SQLAlchemy-backed implementation of the MemoryService."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.db.models import MemoryModel, MessageModel, SessionModel, WorkspaceEdgeModel, WorkspaceObjectModel, generate_uuid
from app.memory.base import MemoryService, MemoryType
from app.memory.embeddings.router import EmbeddingPrivacyBoundaryError, EmbeddingRouter, embedding_router
from app.memory.locks import lock_memory_key
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

    async def _lock_session_graph(self, session_id: str) -> None:
        if self.db.get_bind().dialect.name == "postgresql":
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"workspace-session:{session_id}"},
            )

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

    async def attach_session_to_project(self, session_id: str, project_name: str) -> SessionModel:
        """Associate an existing live session and backfill its graph projection once."""
        await self._lock_session_graph(session_id)
        result = await self.db.execute(select(SessionModel).where(SessionModel.id == session_id))
        session = result.scalar_one_or_none()
        if session is None:
            raise LookupError("Live session not found.")
        if session.project_name and session.project_name != project_name:
            raise ValueError("A live conversation session cannot be moved between projects.")
        session.project_name = project_name

        messages_result = await self.db.execute(
            select(MessageModel)
            .where(MessageModel.session_id == session_id)
            .order_by(MessageModel.created_at, MessageModel.id)
        )
        messages = list(messages_result.scalars())
        message_ids = [message.id for message in messages]
        objects_result = await self.db.execute(
            select(WorkspaceObjectModel).where(WorkspaceObjectModel.source_message_id.in_(message_ids))
        ) if message_ids else None
        objects_by_message = {
            item.source_message_id: item for item in objects_result.scalars()
        } if objects_result is not None else {}
        for message in messages:
            if message.id in objects_by_message:
                continue
            role = message.role
            item = WorkspaceObjectModel(
                project_name=project_name,
                session_id=session_id,
                source_message_id=message.id,
                object_type="conversation_turn",
                created_by=role if role in {"user", "assistant"} else "system",
                title=message.content.strip().splitlines()[0][:255] if message.content.strip() else "Conversation turn",
                content=message.content,
                metadata_json={"role": role},
            )
            self.db.add(item)
            await self.db.flush()
            objects_by_message[message.id] = item

        existing_replies = await self.db.execute(
            select(WorkspaceEdgeModel.source_object_id).where(
                WorkspaceEdgeModel.project_name == project_name,
                WorkspaceEdgeModel.relation_type == "reply",
            )
        )
        replied_user_ids = set(existing_replies.scalars())
        pending_user: Optional[WorkspaceObjectModel] = None
        for message in messages:
            item = objects_by_message[message.id]
            if message.role == "user":
                pending_user = item
            elif message.role == "assistant" and pending_user is not None:
                if pending_user.id not in replied_user_ids:
                    self.db.add(WorkspaceEdgeModel(
                        project_name=project_name,
                        source_object_id=pending_user.id,
                        target_object_id=item.id,
                        relation_type="reply",
                        edge_family="context",
                        created_by="system",
                        metadata_json={},
                    ))
                    replied_user_ids.add(pending_user.id)
                pending_user = None

        existing_continuations = await self.db.execute(
            select(WorkspaceEdgeModel.source_object_id, WorkspaceEdgeModel.target_object_id).where(
                WorkspaceEdgeModel.project_name == project_name,
                WorkspaceEdgeModel.relation_type == "continues",
            )
        )
        continuation_pairs = {(source_id, target_id) for source_id, target_id in existing_continuations.all()}
        previous_assistant: Optional[WorkspaceObjectModel] = None
        for message in messages:
            item = objects_by_message[message.id]
            if message.role == "user":
                pair = (previous_assistant.id, item.id) if previous_assistant else None
                if pair and pair not in continuation_pairs:
                    self.db.add(WorkspaceEdgeModel(
                        project_name=project_name,
                        source_object_id=pair[0],
                        target_object_id=pair[1],
                        relation_type="continues",
                        edge_family="context",
                        created_by="system",
                        metadata_json={},
                    ))
                    continuation_pairs.add(pair)
            elif message.role == "assistant":
                previous_assistant = item

        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MessageModel:
        # Ensure session exists first. Live project chat is indexed as typed
        # workspace objects in the same transaction as its canonical message.
        session = await self.get_or_create_session(session_id)
        await self._lock_session_graph(session_id)
        await self.db.refresh(session)

        msg = MessageModel(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
            metadata_json=metadata or {},
        )
        self.db.add(msg)
        await self.db.flush()

        if session.project_name:
            workspace_object = WorkspaceObjectModel(
                project_name=session.project_name,
                session_id=session_id,
                source_message_id=msg.id,
                object_type="conversation_turn",
                created_by="assistant" if role == "assistant" else "user",
                title=content.strip().splitlines()[0][:255] if content.strip() else "Conversation turn",
                content=content,
                metadata_json={"role": role, **(metadata or {})},
            )
            self.db.add(workspace_object)
            await self.db.flush()

            if role == "user":
                prior_assistant_result = await self.db.execute(
                    select(WorkspaceObjectModel)
                    .where(
                        WorkspaceObjectModel.session_id == session_id,
                        WorkspaceObjectModel.object_type == "conversation_turn",
                        WorkspaceObjectModel.created_by == "assistant",
                    )
                    .order_by(WorkspaceObjectModel.created_at.desc(), WorkspaceObjectModel.id.desc())
                    .limit(1)
                )
                prior_assistant = prior_assistant_result.scalar_one_or_none()
                if prior_assistant is not None:
                    self.db.add(WorkspaceEdgeModel(
                        project_name=session.project_name,
                        source_object_id=prior_assistant.id,
                        target_object_id=workspace_object.id,
                        relation_type="continues",
                        edge_family="context",
                        created_by="system",
                        metadata_json={},
                    ))

            if role == "user" and isinstance(metadata, dict):
                selected_context_ids = metadata.get("context_object_ids")
                if isinstance(selected_context_ids, list):
                    for source_id in dict.fromkeys(
                        value for value in selected_context_ids if isinstance(value, str)
                    ):
                        self.db.add(WorkspaceEdgeModel(
                            project_name=session.project_name,
                            source_object_id=source_id,
                            target_object_id=workspace_object.id,
                            relation_type="context_used",
                            edge_family="context",
                            created_by="system",
                            metadata_json={
                                "run_id": metadata.get("run_id")
                            } if isinstance(metadata.get("run_id"), str) else {},
                        ))

            if role == "assistant":
                prior_users = await self.db.execute(
                    select(WorkspaceObjectModel)
                    .where(
                        WorkspaceObjectModel.session_id == session_id,
                        WorkspaceObjectModel.object_type == "conversation_turn",
                        WorkspaceObjectModel.created_by == "user",
                    )
                    .order_by(WorkspaceObjectModel.created_at.desc())
                )
                replied_result = await self.db.execute(
                    select(WorkspaceEdgeModel.source_object_id).where(
                        WorkspaceEdgeModel.project_name == session.project_name,
                        WorkspaceEdgeModel.relation_type == "reply",
                    )
                )
                replied_user_ids = set(replied_result.scalars())
                for user_object in prior_users.scalars():
                    if metadata and metadata.get("run_id") and user_object.metadata_json.get("run_id") != metadata["run_id"]:
                        continue
                    if user_object.id not in replied_user_ids:
                        self.db.add(WorkspaceEdgeModel(
                            project_name=session.project_name,
                            source_object_id=user_object.id,
                            target_object_id=workspace_object.id,
                            relation_type="reply",
                            edge_family="context",
                            created_by="system",
                            metadata_json={},
                        ))
                        break
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def get_session_messages(self, session_id: str, limit: int = 50) -> List[MessageModel]:
        query = (
            select(MessageModel)
            .where(MessageModel.session_id == session_id)
            .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        # Select the newest window, then present it in chronological conversation order.
        return list(reversed(result.scalars().all()))

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
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.EPISODIC.value,
            MemoryModel.is_active.is_(True),
        )
        if session_id:
            query = query.where(MemoryModel.session_id == session_id)
        query = query.order_by(MemoryModel.created_at.desc(), MemoryModel.id.desc()).limit(limit)
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
        metadata = metadata or {}
        privacy_requirement = metadata.get("privacy_policy")
        vec = embedding
        if vec is not None:
            try:
                self.embedding_router.validate_privacy_requirement(privacy_requirement)
            except EmbeddingPrivacyBoundaryError:
                vec = None
        if vec is None:
            try:
                vec = await self.embedding_router.embed_query(content, privacy_requirement=privacy_requirement)
            except EmbeddingPrivacyBoundaryError:
                vec = None

        memory = MemoryModel(
            session_id=None,
            memory_type=MemoryType.SEMANTIC.value,
            content=content,
            embedding=vec,
            embedding_model=self.embedding_router.current_model_name if vec is not None else None,
            embedding_dim=len(vec) if vec is not None else None,
            project_name=project_name,
            is_active=True,
            metadata_json=metadata,
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
        privacy_requirement: Optional[str] = None,
    ) -> List[MemoryModel]:
        query_vec = embedding
        if query_vec is None:
            try:
                query_vec = await self.embedding_router.embed_query(query, privacy_requirement=privacy_requirement)
            except EmbeddingPrivacyBoundaryError:
                return []

        matches = await self.store.search(
            query_vector=query_vec,
            limit=limit,
            min_similarity=min_similarity,
            project_name=project_name,
            memory_types=[MemoryType.SEMANTIC.value],
            is_active_only=is_active_only,
            embedding_model=self.embedding_router.current_model_name,
            embedding_dim=self.embedding_router.current_dimension,
        )
        return [m[0] for m in matches]

    # --- Memory Lifecycle & Superseding ---
    async def supersede_memory(self, old_memory_id: str, new_memory_id: str) -> None:
        await self.store.supersede(old_memory_id, new_memory_id)

    async def archive_memory(self, memory_id: str) -> None:
        await self.store.archive(memory_id)

    # --- Profile Memory ---
    async def set_profile_fact(self, key: str, value: str, metadata: Optional[Dict[str, Any]] = None) -> MemoryModel:
        await lock_memory_key(self.db, memory_type=MemoryType.PROFILE.value, project_name=None, key=key)
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROFILE.value,
            MemoryModel.project_name.is_(None),
            MemoryModel.key == key,
            MemoryModel.is_active.is_(True),
        )
        result = await self.db.execute(query)
        existing_active = result.scalar_one_or_none()
        new_id = generate_uuid()

        if existing_active:
            await self.db.execute(
                update(MemoryModel)
                .where(MemoryModel.id == existing_active.id, MemoryModel.is_active.is_(True))
                .values(is_active=False, superseded_by_id=new_id)
            )

        new_memory = MemoryModel(
            id=new_id,
            session_id=None,
            memory_type=MemoryType.PROFILE.value,
            key=key,
            content=value,
            is_active=True,
            metadata_json=metadata or {},
            supersedes_id=existing_active.id if existing_active else None,
        )
        self.db.add(new_memory)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(new_memory)
        return new_memory

    async def get_profile_fact(self, key: str) -> Optional[str]:
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROFILE.value,
            MemoryModel.key == key,
            MemoryModel.is_active.is_(True),
        )
        result = await self.db.execute(query)
        memory = result.scalar_one_or_none()
        return memory.content if memory else None

    async def get_profile_memories(self, limit: Optional[int] = None) -> List[MemoryModel]:
        query = (
            select(MemoryModel)
            .where(
                MemoryModel.memory_type == MemoryType.PROFILE.value,
                MemoryModel.is_active.is_(True),
            )
            .order_by(MemoryModel.key.asc(), MemoryModel.id.asc())
        )
        if limit is not None:
            query = query.limit(max(0, limit))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_all_profile_facts(self) -> Dict[str, str]:
        memories = await self.get_profile_memories()
        return {memory.key: memory.content for memory in memories if memory.key}

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

        privacy_requirement = full_metadata.get("privacy_policy")
        vec = embedding
        if vec is not None:
            try:
                self.embedding_router.validate_privacy_requirement(privacy_requirement)
            except EmbeddingPrivacyBoundaryError:
                vec = None
        if vec is None:
            try:
                vec = await self.embedding_router.embed_query(content, privacy_requirement=privacy_requirement)
            except EmbeddingPrivacyBoundaryError:
                vec = None

        full_key = f"{project_name}:{key}"
        await lock_memory_key(
            self.db,
            memory_type=MemoryType.PROJECT.value,
            project_name=project_name,
            key=full_key,
        )
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROJECT.value,
            MemoryModel.project_name == project_name,
            MemoryModel.key == full_key,
            MemoryModel.is_active.is_(True),
        )
        result = await self.db.execute(query)
        existing_active = result.scalar_one_or_none()
        new_id = generate_uuid()

        if existing_active:
            await self.db.execute(
                update(MemoryModel)
                .where(MemoryModel.id == existing_active.id, MemoryModel.is_active.is_(True))
                .values(is_active=False, superseded_by_id=new_id)
            )

        new_memory = MemoryModel(
            id=new_id,
            session_id=None,
            memory_type=MemoryType.PROJECT.value,
            key=full_key,
            content=content,
            embedding=vec,
            embedding_model=self.embedding_router.current_model_name if vec is not None else None,
            embedding_dim=len(vec) if vec is not None else None,
            project_name=project_name,
            is_active=True,
            metadata_json=full_metadata,
            supersedes_id=existing_active.id if existing_active else None,
        )
        self.db.add(new_memory)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(new_memory)
        return new_memory

    async def get_project_memories(
        self,
        project_name: str,
        is_active_only: bool = True,
        limit: Optional[int] = None,
    ) -> List[MemoryModel]:
        query = select(MemoryModel).where(
            MemoryModel.memory_type == MemoryType.PROJECT.value,
            MemoryModel.project_name == project_name,
        )
        if is_active_only:
            query = query.where(MemoryModel.is_active.is_(True))
        query = query.order_by(MemoryModel.confidence.desc(), MemoryModel.updated_at.desc(), MemoryModel.id)
        if limit is not None:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

