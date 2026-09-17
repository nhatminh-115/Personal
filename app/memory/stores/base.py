"""Abstract storage contract for vector-aware semantic memory repositories."""

from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
from app.db.models import MemoryModel


class SemanticMemoryStore(ABC):
    """Clean repository interface decoupling vector storage and search from orchestrator logic."""

    @abstractmethod
    async def store(self, memory: MemoryModel) -> MemoryModel:
        """Persist or update a memory record with vector embedding."""
        pass

    @abstractmethod
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
        """
        Execute nearest-neighbor vector similarity search.
        Returns a list of tuples: (MemoryModel, cosine_similarity_score).
        Filters strictly on embedding_model and embedding_dim to prevent vector space mixing.
        """
        pass

    @abstractmethod
    async def get_by_id(self, memory_id: str) -> Optional[MemoryModel]:
        """Fetch a specific memory item by its primary key."""
        pass

    @abstractmethod
    async def supersede(self, old_memory_id: str, new_memory_id: str) -> None:
        """Atomically link old and new memory items, marking the old memory inactive."""
        pass

    @abstractmethod
    async def archive(self, memory_id: str) -> None:
        """Deactivate a memory record without deleting it from historical audit."""
        pass

    @abstractmethod
    async def delete(self, memory_id: str) -> None:
        """Permanently remove a memory record."""
        pass
