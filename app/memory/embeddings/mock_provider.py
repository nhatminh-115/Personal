"""Deterministic mock embedding provider for tests and reproducible local verification."""

import hashlib
import math
from typing import List, Optional
from app.memory.embeddings.base import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
)


class MockEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic embedding provider producing stable, reproducible unit-length vectors.
    Uses SHA-256 hash seeds to construct consistent pseudo-embeddings without external network calls.
    """

    def __init__(
        self,
        dimension: int = 1536,
        model_name: str = "mock-embedding-v1",
        name: str = "mock",
    ) -> None:
        self._dimension = dimension
        self._model_name = model_name
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _generate_vector(self, text: str) -> List[float]:
        """Produce a deterministic unit-length vector for the input string."""
        if not text:
            # Neutral zero/small vector normalized
            vec = [0.0] * self._dimension
            vec[0] = 1.0
            return vec

        # Use SHA-256 hash to generate deterministic pseudo-random float sequence
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw_vals: List[float] = []

        # Generate enough numbers to fill dimension
        multiplier = (self._dimension // 32) + 1
        extended_bytes = digest * multiplier

        for i in range(self._dimension):
            byte_val = extended_bytes[i]
            # Map byte (0-255) to range [-1.0, 1.0]
            val = (byte_val / 127.5) - 1.0
            raw_vals.append(val)

        # L2-normalize to unit vector
        norm = math.sqrt(sum(x * x for x in raw_vals))
        if norm == 0.0:
            raw_vals[0] = 1.0
            return raw_vals

        return [round(x / norm, 6) for x in raw_vals]

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        embeddings = [self._generate_vector(t) for t in request.texts]
        return EmbeddingResult(
            model=self._model_name,
            dimension=self._dimension,
            embeddings=embeddings,
        )

    async def embed_query(self, text: str) -> List[float]:
        return self._generate_vector(text)
