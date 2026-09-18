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
            return fallback("default_fallback")

        # 1. Explicit model override
        override = getattr(context, "explicit_model_override", None)
        if override:
            if ":" in override:
                prov_part, model_part = override.split(":", 1)
                if prov_part not in available_metadata:
                    raise ValueError(f"Invalid model override: provider '{prov_part}' is not available.")
                return ModelSelection(
                    provider_name=prov_part,
                    model_name=model_part,
                    reason="explicit_model_override",
                    context=context,
                )
            elif override in available_metadata:
                meta = available_metadata[override]
                return ModelSelection(
                    provider_name=override,
                    model_name=meta.default_model,
                    reason="explicit_provider_override",
                    context=context,
                )
            else:
                raise ValueError(f"Invalid model override: provider '{override}' is not available.")

        # 2. Strict Capabilities Filtering
        req_caps = set(context.required_capabilities or [])
        if context.task_type == "coding":
            req_caps.add("code")
        if context.complexity == "complex":
            req_caps.add("reasoning")

        candidates: List[tuple[str, ProviderMetadata]] = list(available_metadata.items())

        if req_caps:
            candidates = [
                (p, m) for p, m in candidates
                if req_caps.issubset(set(m.capabilities))
            ]
            if not candidates:
                raise ValueError(
                    f"No eligible provider found satisfying required capabilities: {sorted(list(req_caps))}"
                )

        # 3. Strict Privacy Requirement (Absolute precedence over cost/latency)
        if context.privacy_requirement == "confidential":
            candidates = [
                (p, m) for p, m in candidates
                if m.privacy_status in ("local", "airgap")
            ]
            if not candidates:
                raise ValueError(
                    "No eligible local/airgap provider found for confidential privacy requirement."
                )

        # 4. Multi-criteria Ranking / Filtering: Cost and Latency
        cost_scores = {"low": 1, "medium": 2, "high": 3}
        latency_scores = {"low": 1, "medium": 2, "high": 3}

        reasons = []
        if context.privacy_requirement == "confidential":
            reasons.append("confidential_privacy")
        if "code" in req_caps:
            reasons.append("coding")
        if "reasoning" in req_caps:
            reasons.append("reasoning")
        if context.latency_preference == "low":
            reasons.append("low_latency")
        if context.cost_preference == "low":
            reasons.append("low_cost")

        def rank_candidate(item: tuple[str, ProviderMetadata]):
            name, meta = item
            c_score = cost_scores.get(meta.cost_class, 2)
            l_score = latency_scores.get(meta.latency_class, 2)
            default_pref = 0 if name == default_provider else 1

            if context.cost_preference == "low" and context.latency_preference == "low":
                return (c_score, l_score, default_pref)
            elif context.cost_preference == "low":
                return (c_score, default_pref)
            elif context.latency_preference == "low":
                return (l_score, default_pref)
            else:
                return (default_pref, c_score)

        candidates.sort(key=rank_candidate)
        chosen_prov, chosen_meta = candidates[0]

        reason_code = "_".join(reasons) + "_matched" if reasons else "default_baseline_matched"
        return ModelSelection(
            provider_name=chosen_prov,
            model_name=chosen_meta.default_model,
            reason=reason_code,
            context=context,
        )
