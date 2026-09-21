"""Deterministic task and model routing policy for AURA."""

from abc import ABC, abstractmethod
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from app.models.base import RoutingContext, PrivacyPolicy, FallbackPolicy, ReasoningEffort, ReasoningPolicy
from app.core.errors import (
    ModelUnavailable,
    ModelCapabilityMismatch,
    NoEligibleRoute,
    ReasoningControlUnsupported,
    PrivacyBoundaryViolation,
    RoutingConfirmationRequired,
)


class ProviderMetadata(BaseModel):
    """Metadata describing capabilities, performance, and privacy of a model provider."""

    name: str
    capabilities: List[str] = Field(default_factory=list)  # e.g. ["code", "reasoning", "general", "fast", "local"]
    context_window: int = 128_000
    cost_class: Literal["low", "medium", "high"] = "medium"
    latency_class: Literal["low", "medium", "high"] = "medium"
    privacy_status: Literal["cloud", "local", "airgap"] = "cloud"
    default_model: str = "default"
    models: List[str] = Field(default_factory=list)
    allow_arbitrary_models: bool = False
    tool_support: Dict[str, str] = Field(default_factory=dict)  # model_name -> 'supported' | 'unsupported' | 'unknown'
    reasoning_support: Dict[str, str] = Field(default_factory=dict)  # model_name -> 'instant' | 'low' | 'medium' | 'high' | 'max' | 'fixed_by_model' | 'unknown'
    vision_support: Dict[str, bool] = Field(default_factory=dict)
    structured_output_support: Dict[str, bool] = Field(default_factory=dict)


class ModelSelection(BaseModel):
    """Result of model routing decision."""

    provider_name: str
    model_name: str
    reason: str
    context: Optional[RoutingContext] = None
    reasoning_effort_selected: Optional[ReasoningEffort] = None


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

        # 1. Explicit model override (LOCK-ALL semantic)
        override = getattr(context, "explicit_model_override", None)
        if override:
            if ":" in override:
                prov_part, model_part = override.split(":", 1)
                if prov_part not in available_metadata:
                    raise ModelUnavailable(f"Invalid model override: provider '{prov_part}' is not available.")
                meta = available_metadata[prov_part]
                
                if meta.models and not meta.allow_arbitrary_models:
                    allowed = set(meta.models)
                    if meta.default_model:
                        allowed.add(meta.default_model)
                    if model_part not in allowed:
                        raise ModelUnavailable(
                            f"Invalid model override: model '{model_part}' is not supported by provider '{prov_part}'. "
                            f"Supported models: {sorted(list(allowed))}"
                        )
                        
                # Check tool capability if tools are required by execution context
                tool_cap = meta.tool_support.get(model_part, "unknown")
                if getattr(context, "requires_tools", False) and tool_cap == "unsupported":
                    raise ModelCapabilityMismatch("Selected override model cannot satisfy required agent/tool capability.")

                # Privacy lock-all enforcement
                if getattr(context, "privacy_requirement", None) == PrivacyPolicy.LOCAL_ONLY and meta.privacy_status == "cloud":
                    raise PrivacyBoundaryViolation("Explicit override selects a cloud model but privacy is local_only.")

                return ModelSelection(
                    provider_name=prov_part,
                    model_name=model_part,
                    reason="explicit_model_override",
                    context=context,
                    reasoning_effort_selected=context.reasoning_effort
                )
            elif override in available_metadata:
                meta = available_metadata[override]
                if getattr(context, "privacy_requirement", None) == PrivacyPolicy.LOCAL_ONLY and meta.privacy_status == "cloud":
                    raise PrivacyBoundaryViolation("Explicit provider override selects a cloud provider but privacy is local_only.")
                return ModelSelection(
                    provider_name=override,
                    model_name=meta.default_model,
                    reason="explicit_provider_override",
                    context=context,
                    reasoning_effort_selected=context.reasoning_effort
                )
            else:
                raise ModelUnavailable(f"Invalid model override: provider '{override}' is not available.")

        candidates: List[tuple[str, str, ProviderMetadata]] = []
        for p, m in available_metadata.items():
            models_to_check = m.models if m.models else [m.default_model]
            for mod in models_to_check:
                candidates.append((p, mod, m))
                
        if not candidates:
            raise NoEligibleRoute("No providers or models registered in routing context.")

        # 2. Privacy Requirement Filtering
        privacy = getattr(context, "privacy_requirement", None) or PrivacyPolicy.PUBLIC
        if privacy in (PrivacyPolicy.CONFIDENTIAL, PrivacyPolicy.LOCAL_ONLY):
            candidates = [(p, mod, m) for p, mod, m in candidates if m.privacy_status in ("local", "airgap")]
            if not candidates:
                raise PrivacyBoundaryViolation(f"No eligible local/airgap provider found for {privacy.value} privacy requirement.")

        # 3. Strict Capabilities Filtering
        req_caps = getattr(context, "required_capabilities", [])
        if req_caps:
            candidates = [
                (p, mod, m) for p, mod, m in candidates
                if all(cap in m.capabilities for cap in req_caps)
            ]
            if not candidates:
                raise ModelCapabilityMismatch(f"No eligible provider found satisfying required capabilities: {req_caps}")
                
        if getattr(context, "requires_tools", False):
            candidates = [(p, mod, m) for p, mod, m in candidates if m.tool_support.get(mod, "unknown") != "unsupported"]
            if not candidates:
                raise ModelCapabilityMismatch("No eligible model found that supports tool calling.")
                
        if getattr(context, "requires_vision", False):
            candidates = [(p, mod, m) for p, mod, m in candidates if m.vision_support.get(mod, False)]
            if not candidates:
                raise ModelCapabilityMismatch("No eligible model found that supports vision.")
                
        if getattr(context, "requires_structured_output", False):
            candidates = [(p, mod, m) for p, mod, m in candidates if m.structured_output_support.get(mod, False)]
            if not candidates:
                raise ModelCapabilityMismatch("No eligible model found that supports structured output.")

        # 4. Fallback Policy Assessment
        fallback_policy = getattr(context, "fallback_policy", None) or FallbackPolicy.CLOUD_ALLOWED
        if fallback_policy == FallbackPolicy.ASK_BEFORE_CLOUD:
            # We don't remove cloud models here, but we mark that if a cloud model wins, we must pause.
            pass
        elif fallback_policy == FallbackPolicy.LOCAL_ONLY:
            candidates = [(p, mod, m) for p, mod, m in candidates if m.privacy_status in ("local", "airgap")]
            if not candidates:
                raise PrivacyBoundaryViolation("No eligible models remain after applying local_only fallback policy.")
        elif fallback_policy == FallbackPolicy.SAME_PROVIDER_ONLY:
            candidates = [(p, mod, m) for p, mod, m in candidates if p == default_provider]
            if not candidates:
                raise NoEligibleRoute("No eligible models remain after applying same_provider_only fallback policy.")

        # 5. Reasoning Effort Resolution & Filtering
        reasoning_policy = getattr(context, "reasoning_policy", None) or ReasoningPolicy.FIXED
        reasoning_effort = getattr(context, "reasoning_effort", None) or ReasoningEffort.LOW
        reasoning_effort_min = getattr(context, "reasoning_effort_min", None)
        reasoning_effort_max = getattr(context, "reasoning_effort_max", None)
        
        valid_reasoning_candidates = []
        for p, mod, m in candidates:
            support = m.reasoning_support.get(mod, "unknown")
            if support == "unsupported":
                continue
                
            if reasoning_policy == ReasoningPolicy.FIXED:
                if support == "fixed_by_model":
                    valid_reasoning_candidates.append((p, mod, m, "fixed_by_model"))
                elif support == reasoning_effort.value:
                    valid_reasoning_candidates.append((p, mod, m, reasoning_effort))
                elif support == "unknown":
                    valid_reasoning_candidates.append((p, mod, m, reasoning_effort)) # Assume it can do it for now
            else: # ADAPTIVE
                if support == "fixed_by_model":
                    valid_reasoning_candidates.append((p, mod, m, "fixed_by_model"))
                elif support == "unknown":
                    valid_reasoning_candidates.append((p, mod, m, reasoning_effort))
                else:
                    # In a real adaptive implementation, this would match dynamic budget.
                    # Here we ensure the model's support falls within bounds or matches the base effort
                    # We will simply pass it through if it supports the base effort.
                    if support == reasoning_effort.value:
                        valid_reasoning_candidates.append((p, mod, m, reasoning_effort))

        if valid_reasoning_candidates:
            pass # We replace candidates list below
        elif reasoning_policy == ReasoningPolicy.FIXED and reasoning_effort != ReasoningEffort.INSTANT:
            raise ReasoningControlUnsupported(f"No eligible provider found satisfying fixed reasoning effort: {reasoning_effort}")
        else:
            # Fall back to base candidates if reasoning constraints were too strict but it's not a hard failure
            valid_reasoning_candidates = [(p, mod, m, None) for p, mod, m in candidates]
            
        # 6. Multi-criteria Ranking / Filtering: Cost and Latency
        cost_scores = {"low": 1, "medium": 2, "high": 3}
        latency_scores = {"low": 1, "medium": 2, "high": 3}

        def rank_candidate(item):
            p, mod, meta, effort_selected = item
            c_score = cost_scores.get(meta.cost_class, 2)
            l_score = latency_scores.get(meta.latency_class, 2)
            default_pref = 0 if p == default_provider else 1

            if context.cost_preference == "low" and context.latency_preference == "low":
                return (c_score, l_score, default_pref)
            elif context.cost_preference == "low":
                return (c_score, default_pref)
            elif context.latency_preference == "low":
                return (l_score, default_pref)
            else:
                return (default_pref, c_score)

        valid_reasoning_candidates.sort(key=rank_candidate)
        if not valid_reasoning_candidates:
            raise NoEligibleRoute("No models left after routing pipeline filters.")
            
        chosen_prov, chosen_model, chosen_meta, chosen_effort = valid_reasoning_candidates[0]

        # Enforce ask_before_cloud
        if fallback_policy == FallbackPolicy.ASK_BEFORE_CLOUD and chosen_meta.privacy_status == "cloud":
            raise RoutingConfirmationRequired(f"Cloud provider {chosen_prov} selected but policy requires confirmation.")

        return ModelSelection(
            provider_name=chosen_prov,
            model_name=chosen_model,
            reason="routing_pipeline_matched",
            context=context,
            reasoning_effort_selected=chosen_effort if isinstance(chosen_effort, ReasoningEffort) else None
        )
