"""Base contracts and DTOs for the provider-neutral embedding layer."""

from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field


class EmbeddingRequest(BaseModel):
    """Request payload for generating vector embeddings."""

    texts: List[str]
    model: Optional[str] = None


class EmbeddingResult(BaseModel):
    """Normalized response containing generated vector embeddings."""

    model: str
    dimension: int
    embeddings: List[List[float]] = Field(default_factory=list)


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'mock', 'openai')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Name of the embedding model produced by this provider."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensionality of the produced vector embeddings."""
        pass

    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        """Generate embeddings for a batch of texts."""
        pass

    @abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a single search query text."""
        pass
