"""OpenAI-compatible embedding provider for production vector generation."""

from typing import List, Optional
import httpx
from app.core.errors import AURAError
from app.memory.embeddings.base import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResult,
)


class EmbeddingProviderError(AURAError):
    """Raised when an embedding provider fails to generate vectors."""
    pass


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Generates vector embeddings via OpenAI-compatible REST API endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "text-embedding-3-small",
        dimension: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model_name = model_name
        self._dimension = dimension
        self._timeout = timeout
        self._name = "openai"

    @property
    def name(self) -> str:
        return self._name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult:
        if not self._api_key:
            raise EmbeddingProviderError("Cannot generate embeddings: OPENAI_API_KEY is not configured.")

        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model or self._model_name,
            "input": request.texts,
            "dimensions": self._dimension,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    raise EmbeddingProviderError(
                        f"OpenAI embedding endpoint returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                data = resp.json()
                raw_items = data.get("data", [])
                raw_items.sort(key=lambda x: x.get("index", 0))
                embeddings = [item["embedding"] for item in raw_items]

                # Validate dimensions
                for idx, vec in enumerate(embeddings):
                    if len(vec) != self._dimension:
                        raise EmbeddingProviderError(
                            f"Embedding vector dimension mismatch: expected {self._dimension}, got {len(vec)} at index {idx}"
                        )

                return EmbeddingResult(
                    model=self._model_name,
                    dimension=self._dimension,
                    embeddings=embeddings,
                )
        except httpx.RequestError as exc:
            raise EmbeddingProviderError(f"Network failure connecting to embedding provider: {exc}") from exc

    async def embed_query(self, text: str) -> List[float]:
        res = await self.embed(EmbeddingRequest(texts=[text]))
        if not res.embeddings:
            raise EmbeddingProviderError("Embedding provider returned empty embeddings for query.")
        return res.embeddings[0]
