"""Deterministic task and model routing policy for AURA."""

from abc import ABC, abstractmethod
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.models.base import RoutingContext


class ProviderMetadata(BaseModel):
    """Metadata describing capabilities, performance, and privacy of a model provider."""

    name: str
    capabilities: List[str] = Field(default_factory=list)  # e.g. ["code", "reasoning", "general", "fast", "local"]
    context_window: int = 128_000
    cost_class: Literal["low", "medium", "high"] = "medium"
    latency_class: Literal["low", "medium", "high"] = "medium"
    privacy_status: Literal["cloud", "local", "airgap"] = "cloud"
    default_model: str = "default"


class ModelSelection(BaseModel):
    """Result of model routing decision."""

    provider_name: str
    model_name: str
    reason: str
    context: Optional[RoutingContext] = None


class RoutingPolicy(ABC):
    """Abstract interface for task/model routing policies."""

    @abstractmethod
    def select(
        self,
        context: Optional[RoutingContext],
        available_metadata: Dict[str, ProviderMetadata],
        default_provider: str,
    ) -> ModelSelection:
        """Select provider and model given context and provider metadata."""
        pass


class DeterministicRoutingPolicy(RoutingPolicy):
    """Deterministic, capability-aware routing policy."""

    def select(
        self,
        context: Optional[RoutingContext],
        available_metadata: Dict[str, ProviderMetadata],
        default_provider: str,
    ) -> ModelSelection:
        # Fallback selection helper
        def fallback(reason: str) -> ModelSelection:
            target_prov = default_provider if default_provider in available_metadata else (next(iter(available_metadata.keys())) if available_metadata else "mock")
            meta = available_metadata.get(target_prov)
            model = meta.default_model if meta else "default"
            return ModelSelection(
                provider_name=target_prov,
                model_name=model,
                reason=reason,
                context=context,
            )

        if not context:
            return fallback("No routing context provided; using default provider.")

        # 1. Explicit model override
        override = getattr(context, "explicit_model_override", None)
        if override:
            if ":" in override:
                prov_part, model_part = override.split(":", 1)
                if prov_part in available_metadata:
                    return ModelSelection(
                        provider_name=prov_part,
                        model_name=model_part,
                        reason=f"Explicit model override '{override}'",
                        context=context,
                    )
            elif override in available_metadata:
                meta = available_metadata[override]
                return ModelSelection(
                    provider_name=override,
                    model_name=meta.default_model,
                    reason=f"Explicit provider override '{override}'",
                    context=context,
                )

        # 2. Strict Privacy Requirement (Confidential/Local)
        if context.privacy_requirement == "confidential":
            local_prov = next(
                (p for p, m in available_metadata.items() if m.privacy_status in ("local", "airgap")),
                None,
            )
            if local_prov:
                return ModelSelection(
                    provider_name=local_prov,
                    model_name=available_metadata[local_prov].default_model,
                    reason="Confidential privacy requirement matched local/airgap provider.",
                    context=context,
                )

        # 3. Coding / Software Engineering Task
        is_coding = context.task_type == "coding" or "code" in context.required_capabilities
        if is_coding:
            coding_prov = next(
                (p for p, m in available_metadata.items() if "code" in m.capabilities),
                None,
            )
            if coding_prov:
                return ModelSelection(
                    provider_name=coding_prov,
                    model_name=available_metadata[coding_prov].default_model,
                    reason="Coding task matched provider with code capability.",
                    context=context,
                )

        # 4. Complex Reasoning Requirement
        if context.complexity == "complex" or "reasoning" in context.required_capabilities:
            reasoning_prov = next(
                (p for p, m in available_metadata.items() if "reasoning" in m.capabilities),
                None,
            )
            if reasoning_prov:
                return ModelSelection(
                    provider_name=reasoning_prov,
                    model_name=available_metadata[reasoning_prov].default_model,
                    reason="High complexity matched provider with advanced reasoning capability.",
                    context=context,
                )

        # 5. Low latency requirement
        if context.latency_preference == "low" or "fast" in context.required_capabilities:
            fast_prov = next(
                (p for p, m in available_metadata.items() if "fast" in m.capabilities or m.latency_class == "low"),
                None,
            )
            if fast_prov:
                return ModelSelection(
                    provider_name=fast_prov,
                    model_name=available_metadata[fast_prov].default_model,
                    reason="Low latency preference matched fast provider.",
                    context=context,
                )

        # 6. Default Fallback
        return fallback("Matched default provider baseline.")
