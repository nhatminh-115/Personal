"""Abstract base class for all model providers."""

from abc import ABC, abstractmethod
from app.models.base import ModelRequest, ModelResponse


class ModelProvider(ABC):
    """Abstract contract for model provider implementations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the provider (e.g., 'mock', 'openai', 'gemini')."""
        pass

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute request and return standardized ModelResponse."""
        pass
