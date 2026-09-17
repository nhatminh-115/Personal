"""Provider-neutral embedding router managing registration, validation, and execution."""

from typing import Dict, List, Optional
from app.core.errors import AURAError
from app.core.logging import logger
from app.core.settings import settings
from app.memory.embeddings.base import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
)
from app.memory.embeddings.mock_provider import MockEmbeddingProvider
from app.memory.embeddings.openai_provider import OpenAIEmbeddingProvider


class EmbeddingModelMismatchError(AURAError):
    """Raised when an operation attempts to compare or mix vectors from different embedding models."""
    pass


class EmbeddingRouter:
    """
    Manages vector embedding providers, enforces model identity tracking,
    and guarantees dimension consistency across memories.
    """

    def __init__(
        self,
        providers: Optional[Dict[str, EmbeddingProvider]] = None,
        default_provider: Optional[str] = None,
    ) -> None:
        self._providers: Dict[str, EmbeddingProvider] = {}
        self._default_provider = default_provider or settings.EMBEDDING_PROVIDER

        if providers:
            for name, provider in providers.items():
                self.register_provider(name, provider)
        else:
            # Default initialization from settings
            self.register_provider(
                "mock",
                MockEmbeddingProvider(
                    dimension=settings.EMBEDDING_DIMENSION,
                    model_name=settings.EMBEDDING_MODEL_NAME,
                ),
            )
            self.register_provider(
                "openai",
                OpenAIEmbeddingProvider(
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                    model_name=settings.EMBEDDING_MODEL_NAME,
                    dimension=settings.EMBEDDING_DIMENSION,
                ),
            )

    def register_provider(self, name: str, provider: EmbeddingProvider) -> None:
        self._providers[name] = provider
        logger.info(
            f"Registered embedding provider '{name}' (model: {provider.model_name}, dim: {provider.dimension})",
            extra={"provider": name, "model": provider.model_name, "dim": provider.dimension},
        )

    def get_provider(self, name: Optional[str] = None) -> EmbeddingProvider:
        provider_name = name or self._default_provider
        if provider_name not in self._providers:
            raise AURAError(f"Embedding provider '{provider_name}' is not registered.")
        return self._providers[provider_name]

    @property
    def default_provider_name(self) -> str:
        return self._default_provider

    @property
    def current_model_name(self) -> str:
        return self.get_provider().model_name

    @property
    def current_dimension(self) -> int:
        return self.get_provider().dimension

    async def embed(
        self,
        texts: List[str],
        provider_name: Optional[str] = None,
    ) -> EmbeddingResult:
        """Batch embed a list of texts using the selected provider."""
        provider = self.get_provider(provider_name)
        result = await provider.embed(EmbeddingRequest(texts=texts))

        # Validate that the returned dimension strictly matches expectations
        if result.dimension != provider.dimension:
            raise EmbeddingModelMismatchError(
                f"Embedding dimension mismatch: expected {provider.dimension}, got {result.dimension}"
            )
        return result

    async def embed_query(
        self,
        text: str,
        provider_name: Optional[str] = None,
    ) -> List[float]:
        """Embed a single query string for semantic vector search."""
        provider = self.get_provider(provider_name)
        vec = await provider.embed_query(text)
        if len(vec) != provider.dimension:
            raise EmbeddingModelMismatchError(
                f"Query embedding dimension mismatch: expected {provider.dimension}, got {len(vec)}"
            )
        return vec

    def validate_vector_compatibility(self, vector: List[float], model_name: Optional[str] = None) -> None:
        """Validate that a candidate vector matches the active embedding model and dimension."""
        provider = self.get_provider()
        if len(vector) != provider.dimension:
            raise EmbeddingModelMismatchError(
                f"Vector dimension {len(vector)} does not match active embedding model dimension {provider.dimension}"
            )
        if model_name and model_name != provider.model_name:
            raise EmbeddingModelMismatchError(
                f"Vector model '{model_name}' does not match active model '{provider.model_name}'. Re-embedding required."
            )


# Global singleton instance
embedding_router = EmbeddingRouter()
