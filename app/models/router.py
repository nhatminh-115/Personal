"""ModelRouter abstraction for routing requests to providers."""

from typing import Dict, Optional, Tuple
from app.core.errors import ProviderError
from app.core.settings import settings
from app.models.base import ModelRequest, ModelResponse, RoutingContext
from app.models.mock_provider import MockModelProvider
from app.models.openai_provider import OpenAICompatibleProvider
from app.models.provider import ModelProvider
from app.models.routing_policy import (
    DeterministicRoutingPolicy,
    ModelSelection,
    ProviderMetadata,
    RoutingPolicy,
)


class ModelRouter:
    """Routes model requests to appropriate provider adapters using a configurable policy."""

    def __init__(
        self,
        default_provider_name: str | None = None,
        default_provider: str | None = None,
        providers: Dict[str, ModelProvider] | None = None,
        policy: Optional[RoutingPolicy] = None,
    ) -> None:
        self._providers: Dict[str, ModelProvider] = {}
        self._metadata: Dict[str, ProviderMetadata] = {}
        self._policy = policy or DeterministicRoutingPolicy()
        self._default_provider_name = default_provider_name or default_provider or settings.MODEL_PROVIDER

        if providers:
            for p in providers.values():
                self.register_provider(p)
        else:
            # Register standard providers with metadata
            self.register_provider(
                MockModelProvider(),
                ProviderMetadata(
                    name="mock",
                    capabilities=["general", "code", "reasoning", "fast", "local"],
                    cost_class="low",
                    latency_class="low",
                    privacy_status="local",
                    default_model="mock-default",
                ),
            )
            self.register_provider(
                OpenAICompatibleProvider(),
                ProviderMetadata(
                    name="openai",
                    capabilities=["general", "code", "reasoning"],
                    cost_class="medium",
                    latency_class="medium",
                    privacy_status="cloud",
                    default_model=settings.OPENAI_MODEL_NAME or "gpt-4o",
                ),
            )

    def register_provider(
        self,
        provider: ModelProvider,
        metadata: Optional[ProviderMetadata] = None,
    ) -> None:
        """Register a provider instance with optional metadata."""
        self._providers[provider.name] = provider
        if metadata:
            self._metadata[provider.name] = metadata
        elif provider.name not in self._metadata:
            self._metadata[provider.name] = ProviderMetadata(
                name=provider.name,
                capabilities=["general"],
                default_model="default",
            )

    def get_provider(self, name: str | None = None) -> ModelProvider:
        """Retrieve provider by name, falling back to default."""
        target_name = name or self._default_provider_name
        if target_name not in self._providers:
            raise ProviderError(f"Model provider '{target_name}' is not registered.")
        return self._providers[target_name]

    def select_model_for_task(
        self,
        context: Optional[RoutingContext],
    ) -> Tuple[ModelProvider, ModelSelection]:
        """Use deterministic routing policy to select provider and model for given context."""
        selection = self._policy.select(
            context=context,
            available_metadata=self._metadata,
            default_provider=self._default_provider_name,
        )
        provider = self.get_provider(selection.provider_name)
        return provider, selection

    async def route(
        self,
        request: ModelRequest,
        provider_name: str | None = None,
        routing_context: RoutingContext | None = None,
    ) -> ModelResponse:
        """Route request to the target provider with optional routing context and policy selection."""
        ctx = routing_context or request.routing_context
        if ctx and not request.routing_context:
            request.routing_context = ctx

        # If explicit provider specified, use it directly; otherwise use routing policy
        if provider_name:
            provider = self.get_provider(provider_name)
        else:
            provider, selection = self.select_model_for_task(ctx)
            from app.core.logging import logger
            logger.info(
                f"Model routed to '{selection.provider_name}' ({selection.model_name}): {selection.reason}",
                extra={
                    "provider": selection.provider_name,
                    "model": selection.model_name,
                    "reason": selection.reason,
                    "run_id": ctx.run_id if ctx else None,
                },
            )

        return await provider.generate(request)


# Singleton default router
model_router = ModelRouter()
