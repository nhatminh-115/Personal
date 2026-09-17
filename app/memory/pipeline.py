"""Conservative memory candidate extraction and superseding pipeline."""

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.logging import logger
from app.db.models import MemoryModel
from app.memory.base import MemoryService, MemoryType


class MemoryCandidate(BaseModel):
    """Candidate knowledge extracted from an interaction turn."""

    memory_type: MemoryType
    key: Optional[str] = None
    content: str
    project_name: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryCandidatePipeline:
    """
    Conservative extraction pipeline.
    Avoids permanently storing noisy casual conversation.
    Differentiates explicit user directives, durable project facts, and profile preferences.
    """

    # Patterns for explicit remember instructions
    EXPLICIT_REMEMBER_PATTERNS = [
        r"(?:please\s+)?(?:remember|note(?:\s+down)?|keep\s+in\s+mind)\s+(?:that\s+)?(.+)",
        r"(?:hãy\s+)?(?:ghi\s+nhớ|lưu\s+ý|nhớ)(?:\s+rằng)?\s*[:\s]\s*(.+)",
    ]

    # Patterns for project facts
    PROJECT_PATTERNS = [
        r"project\s+([A-Za-z0-9_-]+)\s+(?:uses|is|runs|targets|upgraded\s+to|configured\s+with)\s+(.+)",
        r"dự\s+án\s+([A-Za-z0-9_-]+)\s+(?:sử\s+dụng|dùng|chạy|nâng\s+cấp\s+lên)\s+(.+)",
    ]

    # Patterns for profile preferences
    PROFILE_PATTERNS = [
        r"i\s+(?:prefer|like|always\s+use)\s+(.+)",
        r"my\s+preferred\s+([A-Za-z0-9_-]+)\s+is\s+(.+)",
        r"tôi\s+(?:thích|ưu\s+tiên|chuộng)\s+(.+)",
    ]

    def extract_candidates(
        self,
        user_message: str,
        assistant_response: Optional[str] = None,
        active_project: Optional[str] = None,
    ) -> List[MemoryCandidate]:
        """Extract conservative memory candidates from a user turn."""
        text = user_message.strip()
        candidates: List[MemoryCandidate] = []

        # 1. Check for explicit 'remember' commands
        explicit_content = None
        for pat in self.EXPLICIT_REMEMBER_PATTERNS:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                explicit_content = m.group(1).strip().rstrip(".")
                break

        target_text = explicit_content if explicit_content is not None else text

        # If it was an explicit request OR mentions project/preference:
        # Check for project-scoped knowledge
        matched_project = False
        for pat in self.PROJECT_PATTERNS:
            pm = re.search(pat, target_text, re.IGNORECASE)
            if pm:
                p_name = pm.group(1).strip()
                p_fact = pm.group(0).strip()
                # Derive candidate key
                p_key = "general"
                if "python" in p_fact.lower():
                    p_key = "python_version"
                elif "node" in p_fact.lower():
                    p_key = "node_version"
                elif "database" in p_fact.lower() or "db" in p_fact.lower():
                    p_key = "database"

                candidates.append(
                    MemoryCandidate(
                        memory_type=MemoryType.PROJECT,
                        key=p_key,
                        content=p_fact,
                        project_name=p_name,
                        confidence=1.0 if explicit_content else 0.85,
                        metadata={"explicit": explicit_content is not None},
                    )
                )
                matched_project = True
                break

        if not matched_project and explicit_content:
            # Check for profile preference
            matched_profile = False
            for pat in self.PROFILE_PATTERNS:
                prm = re.search(pat, explicit_content, re.IGNORECASE)
                if prm:
                    pref_val = prm.group(1).strip()
                    candidates.append(
                        MemoryCandidate(
                            memory_type=MemoryType.PROFILE,
                            key="user_preference",
                            content=pref_val,
                            confidence=1.0,
                            metadata={"explicit": True},
                        )
                    )
                    matched_profile = True
                    break

            if not matched_profile:
                # Default explicit directive to semantic memory
                candidates.append(
                    MemoryCandidate(
                        memory_type=MemoryType.SEMANTIC,
                        content=explicit_content,
                        project_name=active_project,
                        confidence=1.0,
                        metadata={"explicit": True},
                    )
                )

        return candidates

    async def process_and_commit(
        self,
        candidates: List[MemoryCandidate],
        session_id: str,
        run_id: str,
        memory_service: MemoryService,
    ) -> List[MemoryModel]:
        """Commit memory candidates with automatic superseding and deduplication."""
        saved_memories: List[MemoryModel] = []

        for cand in candidates:
            metadata = dict(cand.metadata)
            metadata["source_session_id"] = session_id
            metadata["source_run_id"] = run_id
            metadata["confidence"] = cand.confidence

            if cand.memory_type == MemoryType.PROJECT and cand.project_name:
                key = cand.key or "general"
                # Check for existing project memories under this project and key to supersede
                existing_memories = await memory_service.get_project_memories(cand.project_name, is_active_only=True)
                old_matching = [m for m in existing_memories if m.key == f"{cand.project_name}:{key}"]

                new_mem = await memory_service.store_project_memory(
                    project_name=cand.project_name,
                    key=key,
                    content=cand.content,
                    metadata=metadata,
                )

                for old_m in old_matching:
                    if old_m.id != new_mem.id:
                        logger.info(
                            f"Superseding older project memory '{old_m.id}' with '{new_mem.id}' for project '{cand.project_name}'",
                            extra={"old_id": old_m.id, "new_id": new_mem.id},
                        )
                        await memory_service.supersede_memory(old_m.id, new_mem.id)

                saved_memories.append(new_mem)

            elif cand.memory_type == MemoryType.PROFILE and cand.key:
                mem = await memory_service.set_profile_fact(
                    key=cand.key,
                    value=cand.content,
                    metadata=metadata,
                )
                saved_memories.append(mem)

            elif cand.memory_type == MemoryType.SEMANTIC:
                # Store semantic memory
                mem = await memory_service.store_semantic_memory(
                    content=cand.content,
                    metadata=metadata,
                    project_name=cand.project_name,
                )
                saved_memories.append(mem)

        return saved_memories
