"""ModelRouter abstraction for routing requests to providers."""

from typing import Dict
from app.core.errors import ProviderError
from app.core.settings import settings
from app.models.base import ModelRequest, ModelResponse
from app.models.mock_provider import MockModelProvider
from app.models.openai_provider import OpenAICompatibleProvider
from app.models.provider import ModelProvider


class ModelRouter:
    """Routes model requests to appropriate provider adapters."""

    def __init__(self, default_provider_name: str | None = None) -> None:
        self._providers: Dict[str, ModelProvider] = {}
        self._default_provider_name = default_provider_name or settings.MODEL_PROVIDER

        # Register standard providers
        self.register_provider(MockModelProvider())
        self.register_provider(OpenAICompatibleProvider())

    def register_provider(self, provider: ModelProvider) -> None:
        """Register a provider instance."""
        self._providers[provider.name] = provider

    def get_provider(self, name: str | None = None) -> ModelProvider:
        """Retrieve provider by name, falling back to default."""
        target_name = name or self._default_provider_name
        if target_name not in self._providers:
            raise ProviderError(f"Model provider '{target_name}' is not registered.")
        return self._providers[target_name]

    async def route(self, request: ModelRequest, provider_name: str | None = None) -> ModelResponse:
        """Route request to the target provider."""
        provider = self.get_provider(provider_name)
        return await provider.generate(request)


# Singleton default router
model_router = ModelRouter()
