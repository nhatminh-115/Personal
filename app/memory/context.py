"""Typed context assembly combining multi-tier memory for orchestrator reasoning."""

from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from app.db.models import MemoryModel
from app.memory.base import MemoryService, MemoryType


class AssembledContext(BaseModel):
    """Structured, typed memory context assembled for an execution turn."""

    session_id: str
    project_name: Optional[str] = None
    working_messages: List[Dict[str, Any]] = Field(default_factory=list)
    episodes: List[str] = Field(default_factory=list)
    semantic_items: List[Tuple[str, float]] = Field(default_factory=list)
    profile_facts: Dict[str, str] = Field(default_factory=dict)
    project_facts: List[str] = Field(default_factory=list)

    def format_for_system_prompt(self) -> str:
        """Format non-working memory context into a deterministic, human-readable system prompt section."""
        sections: List[str] = []

        if self.profile_facts:
            lines = [f"- {k}: {v}" for k, v in sorted(self.profile_facts.items())]
            sections.append("### User Profile & Preferences:\n" + "\n".join(lines))

        if self.project_facts:
            proj_header = f"### Project Knowledge ({self.project_name}):" if self.project_name else "### Project Knowledge:"
            lines = [f"- {fact}" for fact in self.project_facts]
            sections.append(f"{proj_header}\n" + "\n".join(lines))

        if self.semantic_items:
            lines = [f"- {item} (similarity: {score:.2f})" for item, score in self.semantic_items]
            sections.append("### Relevant Factual Knowledge:\n" + "\n".join(lines))

        if self.episodes:
            lines = [f"- {ep}" for ep in self.episodes]
            sections.append("### Recent Interaction History:\n" + "\n".join(lines))

        return "\n\n".join(sections)


class ContextAssembler:
    """
    Retrieves and synthesizes relevant context across all five cognitive tiers
    with scoring, thresholding, project scoping, and duplicate suppression.
    """

    def __init__(self, memory_service: MemoryService) -> None:
        self.mem_service = memory_service

    async def assemble_context(
        self,
        session_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        semantic_top_k: int = 5,
        semantic_threshold: float = 0.5,
        recent_episodes_limit: int = 3,
        working_history_limit: int = 20,
    ) -> AssembledContext:
        """Assemble structured context for the given user message."""
        context = AssembledContext(session_id=session_id, project_name=project_name)

        # 1. Working Memory: Recent conversation turns
        db_msgs = await self.mem_service.get_session_messages(session_id, limit=working_history_limit)
        context.working_messages = [{"role": m.role, "content": m.content} for m in db_msgs]

        # 2. Profile Memory: Global preferences (deduplicated by key)
        context.profile_facts = await self.mem_service.get_all_profile_facts()

        # 3. Project Memory: Strictly scoped to project_name if provided
        if project_name:
            proj_memories = await self.mem_service.get_project_memories(project_name, is_active_only=True)
            seen_facts = set()
            for pm in proj_memories:
                if pm.content not in seen_facts:
                    context.project_facts.append(pm.content)
                    seen_facts.add(pm.content)

        # 4. Episodic Memory: Narrative records of recent milestones
        episodes = await self.mem_service.get_recent_episodes(session_id=session_id, limit=recent_episodes_limit)
        context.episodes = [ep.content for ep in episodes if ep.content]

        # 5. Semantic Memory: Nearest-neighbor vector similarity
        if user_message.strip():
            # If the service provides store-level scoring, access store directly or use search
            store = getattr(self.mem_service, "store", None)
            embedding_router = getattr(self.mem_service, "embedding_router", None)

            if store and embedding_router:
                query_vec = await embedding_router.embed_query(user_message)
                search_types = (
                    [MemoryType.SEMANTIC.value, MemoryType.PROJECT.value]
                    if project_name
                    else [MemoryType.SEMANTIC.value]
                )
                matches = await store.search(
                    query_vector=query_vec,
                    limit=semantic_top_k,
                    min_similarity=semantic_threshold,
                    project_name=project_name,
                    memory_types=search_types,
                    is_active_only=True,
                    embedding_model=embedding_router.current_model_name,
                    embedding_dim=embedding_router.current_dimension,
                )
                seen_semantic = set()
                for mem, sim in matches:
                    if mem.content not in seen_semantic and mem.content not in context.project_facts:
                        context.semantic_items.append((mem.content, sim))
                        seen_semantic.add(mem.content)
            else:
                raw_memories = await self.mem_service.search_semantic_memory(
                    query=user_message,
                    limit=semantic_top_k,
                    min_similarity=semantic_threshold,
                    project_name=project_name,
                    is_active_only=True,
                )
                for mem in raw_memories:
                    if mem.content not in context.project_facts:
                        context.semantic_items.append((mem.content, 1.0))

        return context
