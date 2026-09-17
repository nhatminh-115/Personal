"""Embedding abstraction layer for provider-neutral vectorization."""

from app.memory.embeddings.base import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
)
from app.memory.embeddings.mock_provider import MockEmbeddingProvider
from app.memory.embeddings.openai_provider import OpenAIEmbeddingProvider
from app.memory.embeddings.router import EmbeddingRouter, embedding_router

__all__ = [
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResult",
    "MockEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "EmbeddingRouter",
    "embedding_router",
]
