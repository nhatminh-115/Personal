"""Memory subsystem domain types and service contract."""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.db.models import MemoryModel, MessageModel, SessionModel


class MemoryType(str, Enum):
    """Five cognitive memory tiers."""
    WORKING = "working"        # Ephemeral per-turn or active conversation buffer
    EPISODIC = "episodic"      # Narrative records of prior interactions and runs
    SEMANTIC = "semantic"      # Durable extracted facts, searchable via embeddings
    PROFILE = "profile"        # Persistent user preferences and profile facts
    PROJECT = "project"        # Context and knowledge scoped to a specific project


class MemoryItem(BaseModel):
    """Normalized memory data representation."""

    id: str
    session_id: Optional[str] = None
    memory_type: MemoryType
    key: Optional[str] = None
    content: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MemoryService(ABC):
    """Contract for multi-tier memory operations."""

    # --- Working Memory (Sessions & Messages) ---
    @abstractmethod
    async def get_or_create_session(self, session_id: str, title: Optional[str] = None) -> SessionModel:
        """Fetch an existing session or initialize a new one."""
        pass

    @abstractmethod
    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: Optional[int] = None,
    ) -> MessageModel:
        """Persist a conversation turn message."""
        pass

    @abstractmethod
    async def get_session_messages(self, session_id: str, limit: int = 50) -> List[MessageModel]:
        """Fetch the chronological message history for an active session."""
        pass

    # --- Episodic Memory ---
    @abstractmethod
    async def record_episodic_memory(
        self,
        session_id: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryModel:
        """Record an episode summary of a completed run or milestone."""
        pass

    @abstractmethod
    async def get_recent_episodes(self, session_id: Optional[str] = None, limit: int = 5) -> List[MemoryModel]:
        """Retrieve recent episodic interaction records."""
        pass

    # --- Semantic Memory (Interface) ---
    @abstractmethod
    async def store_semantic_memory(
        self,
        content: str,
        embedding: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryModel:
        """Store durable knowledge for semantic vector retrieval."""
        pass

    @abstractmethod
    async def search_semantic_memory(
        self,
        query: str,
        embedding: Optional[List[float]] = None,
        limit: int = 5,
    ) -> List[MemoryModel]:
        """Query semantic knowledge via keyword or vector similarity."""
        pass

    # --- Profile Memory (Interface) ---
    @abstractmethod
    async def set_profile_fact(self, key: str, value: str, metadata: Optional[Dict[str, Any]] = None) -> MemoryModel:
        """Set a user preference or profile attribute."""
        pass

    @abstractmethod
    async def get_profile_fact(self, key: str) -> Optional[str]:
        """Retrieve a specific profile attribute by key."""
        pass

    @abstractmethod
    async def get_all_profile_facts(self) -> Dict[str, str]:
        """Retrieve all known user profile preferences."""
        pass

    # --- Project Memory (Interface) ---
    @abstractmethod
    async def store_project_memory(
        self,
        project_name: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryModel:
        """Record project-scoped knowledge."""
        pass

    @abstractmethod
    async def get_project_memories(self, project_name: str) -> List[MemoryModel]:
        """Retrieve all knowledge scoped to a specific project."""
        pass
