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
    reasoning_effort_selected: Optional[str] = None


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
                target_prov, target_model = override.split(":", 1)
                if target_prov not in available_metadata:
                    raise ModelUnavailable(f"Invalid model override: provider '{target_prov}' is not available.")
                meta = available_metadata[target_prov]
                if meta.models and not meta.allow_arbitrary_models:
                    allowed = set(meta.models)
                    if meta.default_model:
                        allowed.add(meta.default_model)
                    if target_model not in allowed:
                        raise ModelUnavailable(
                            f"Invalid model override: model '{target_model}' is not supported by provider '{target_prov}'. "
                            f"Supported models: {sorted(list(allowed))}"
                        )
                reason = "explicit_model_override"
            elif override in available_metadata:
                target_prov = override
                meta = available_metadata[target_prov]
                target_model = meta.default_model
                reason = "explicit_provider_override"
            else:
                raise ModelUnavailable(f"Invalid model override: provider '{override}' is not available.")

            # Hard capability and boundary checks on explicit override:
            # A user choosing an exact model/provider override must not bypass hard capability constraints.
            # NO fallback is permitted on failure.
            privacy = getattr(context, "privacy_requirement", None) or PrivacyPolicy.PUBLIC
            if privacy in (PrivacyPolicy.CONFIDENTIAL, PrivacyPolicy.LOCAL_ONLY):
                if meta.privacy_status not in ("local", "airgap"):
                    raise PrivacyBoundaryViolation(
                        f"Explicit override selects cloud provider '{target_prov}' but privacy is {privacy.value}."
                    )

            req_caps = getattr(context, "required_capabilities", [])
            if req_caps:
                missing_caps = [c for c in req_caps if c not in meta.capabilities]
                if missing_caps:
                    raise ModelCapabilityMismatch(
                        f"Explicit override model '{target_model}' does not satisfy required capabilities: {missing_caps}"
                    )

            if getattr(context, "requires_tools", False):
                tool_cap = meta.tool_support.get(target_model, "unknown")
                if tool_cap == "unsupported":
                    raise ModelCapabilityMismatch(
                        "Selected override model cannot satisfy required agent/tool capability."
                    )

            if getattr(context, "requires_vision", False):
                vision_cap = meta.vision_support.get(target_model, False)
                if not vision_cap:
                    raise ModelCapabilityMismatch(
                        f"Explicit override model '{target_model}' does not support vision."
                    )

            if getattr(context, "requires_structured_output", False):
                struct_cap = meta.structured_output_support.get(target_model, False)
                if not struct_cap:
                    raise ModelCapabilityMismatch(
                        f"Explicit override model '{target_model}' does not support structured output."
                    )

            if getattr(context, "requires_long_context", False):
                if "long_context" not in meta.capabilities:
                    raise ModelCapabilityMismatch(
                        f"Explicit override provider '{target_prov}' does not satisfy long_context capability."
                    )

            # Explicit-override reasoning truthfulness
            EFFORT_ORDER = [
                ReasoningEffort.INSTANT,
                ReasoningEffort.LOW,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.HIGH,
                ReasoningEffort.MAX,
            ]
            EFFORT_STRS = [e.value for e in EFFORT_ORDER]
            support = meta.reasoning_support.get(target_model, "unknown")
            user_fixed_effort = getattr(context, "reasoning_effort", None)
            reasoning_policy = getattr(context, "reasoning_policy", None)

            if user_fixed_effort is not None or reasoning_policy == ReasoningPolicy.FIXED:
                eff_val = user_fixed_effort.value if hasattr(user_fixed_effort, "value") else str(user_fixed_effort or ReasoningEffort.MEDIUM.value)
                if eff_val == ReasoningEffort.INSTANT.value:
                    if support == "unsupported":
                        raise ReasoningControlUnsupported(f"Explicit override model '{target_model}' does not support reasoning.")
                    elif support == "fixed_by_model":
                        resolved_effort = "fixed_by_model"
                    elif support == "unknown":
                        resolved_effort = "unknown"
                    else:
                        resolved_effort = eff_val
                else:
                    if support in ("unsupported", "fixed_by_model", "unknown"):
                        raise ReasoningControlUnsupported(
                            f"Explicit override model '{target_model}' has reasoning_support='{support}', cannot satisfy controllable fixed reasoning '{eff_val}'."
                        )
                    if support not in EFFORT_STRS:
                        raise ReasoningControlUnsupported(f"Explicit override model '{target_model}' has unrecognized reasoning_support='{support}'.")
                    if eff_val not in EFFORT_STRS:
                        raise ReasoningControlUnsupported(f"Requested reasoning effort '{eff_val}' is invalid.")
                    model_max_idx = EFFORT_STRS.index(support)
                    req_idx = EFFORT_STRS.index(eff_val)
                    if req_idx > model_max_idx:
                        raise ReasoningControlUnsupported(
                            f"Explicit override model '{target_model}' max reasoning support is '{support}', cannot satisfy requested '{eff_val}'."
                        )
                    resolved_effort = eff_val
            elif reasoning_policy == ReasoningPolicy.ADAPTIVE:
                if support == "unsupported":
                    resolved_effort = "unsupported"
                elif support == "fixed_by_model":
                    resolved_effort = "fixed_by_model"
                elif support == "unknown":
                    resolved_effort = "unknown"
                else:
                    comp = getattr(context, "complexity", None)
                    if comp == "simple":
                        target_effort = ReasoningEffort.LOW
                    elif comp == "complex":
                        target_effort = ReasoningEffort.HIGH
                    else:
                        target_effort = ReasoningEffort.MEDIUM

                    reasoning_effort_min = getattr(context, "reasoning_effort_min", None) or ReasoningEffort.LOW
                    if isinstance(reasoning_effort_min, str):
                        try:
                            reasoning_effort_min = ReasoningEffort(reasoning_effort_min)
                        except ValueError:
                            pass
                    reasoning_effort_max = getattr(context, "reasoning_effort_max", None) or ReasoningEffort.HIGH
                    if isinstance(reasoning_effort_max, str):
                        try:
                            reasoning_effort_max = ReasoningEffort(reasoning_effort_max)
                        except ValueError:
                            pass

                    min_idx = EFFORT_ORDER.index(reasoning_effort_min) if reasoning_effort_min in EFFORT_ORDER else 1
                    max_idx = EFFORT_ORDER.index(reasoning_effort_max) if reasoning_effort_max in EFFORT_ORDER else 3
                    target_idx = EFFORT_ORDER.index(target_effort)
                    profile_target_idx = max(min_idx, min(max_idx, target_idx))

                    if support in EFFORT_STRS:
                        model_max_idx = EFFORT_STRS.index(support)
                        selected_idx = min(profile_target_idx, model_max_idx)
                        resolved_effort = EFFORT_STRS[selected_idx]
                    else:
                        resolved_effort = support
            else:
                if support == "fixed_by_model":
                    resolved_effort = "fixed_by_model"
                elif support == "unknown":
                    resolved_effort = "unknown"
                elif support in EFFORT_STRS:
                    if user_fixed_effort:
                        eff_val = user_fixed_effort.value if hasattr(user_fixed_effort, "value") else str(user_fixed_effort)
                        resolved_effort = eff_val
                    else:
                        resolved_effort = None
                else:
                    resolved_effort = None

            return ModelSelection(
                provider_name=target_prov,
                model_name=target_model,
                reason=reason,
                context=context,
                reasoning_effort_selected=resolved_effort,
            )

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

        # 3b. Long Context Capability Filtering (Requirement 8)
        if getattr(context, "requires_long_context", False):
            candidates = [(p, mod, m) for p, mod, m in candidates if "long_context" in m.capabilities]
            if not candidates:
                raise ModelCapabilityMismatch("No eligible provider found satisfying long_context capability.")

        # 4. Fallback Policy Assessment (Requirement 9)
        fallback_policy = getattr(context, "fallback_policy", None) or FallbackPolicy.CLOUD_ALLOWED
        if fallback_policy == FallbackPolicy.NONE:
            # If active route/provider assigned, NONE strictly blocks switching to alternative providers/models
            target_prov = getattr(context, "assigned_provider", None) or default_provider
            candidates = [(p, mod, m) for p, mod, m in candidates if p == target_prov]
            if not candidates:
                raise NoEligibleRoute("Assigned route unavailable and fallback policy is NONE.")
        elif fallback_policy == FallbackPolicy.ASK_BEFORE_CLOUD:
            pass
        elif fallback_policy == FallbackPolicy.LOCAL_ONLY:
            candidates = [(p, mod, m) for p, mod, m in candidates if m.privacy_status in ("local", "airgap")]
            if not candidates:
                raise PrivacyBoundaryViolation("No eligible models remain after applying local_only fallback policy.")
        elif fallback_policy == FallbackPolicy.SAME_PROVIDER_ONLY:
            candidates = [(p, mod, m) for p, mod, m in candidates if p == default_provider]
            if not candidates:
                raise NoEligibleRoute("No eligible models remain after applying same_provider_only fallback policy.")

        # 5. Reasoning Effort Resolution & Filtering (Requirements 3 & 5)
        EFFORT_ORDER = [
            ReasoningEffort.INSTANT,
            ReasoningEffort.LOW,
            ReasoningEffort.MEDIUM,
            ReasoningEffort.HIGH,
            ReasoningEffort.MAX,
        ]
        EFFORT_STRS = [e.value for e in EFFORT_ORDER]
        
        user_fixed_effort = getattr(context, "reasoning_effort", None)
        reasoning_policy = getattr(context, "reasoning_policy", None)
        
        valid_reasoning_candidates = []

        if reasoning_policy == ReasoningPolicy.ADAPTIVE:
            comp = getattr(context, "complexity", None)
            if comp == "simple":
                target_effort = ReasoningEffort.LOW
            elif comp == "complex":
                target_effort = ReasoningEffort.HIGH
            else:
                target_effort = ReasoningEffort.MEDIUM

            reasoning_effort_min = getattr(context, "reasoning_effort_min", None) or ReasoningEffort.LOW
            if isinstance(reasoning_effort_min, str):
                try:
                    reasoning_effort_min = ReasoningEffort(reasoning_effort_min)
                except ValueError:
                    pass
            reasoning_effort_max = getattr(context, "reasoning_effort_max", None) or ReasoningEffort.HIGH
            if isinstance(reasoning_effort_max, str):
                try:
                    reasoning_effort_max = ReasoningEffort(reasoning_effort_max)
                except ValueError:
                    pass

            min_idx = EFFORT_ORDER.index(reasoning_effort_min) if reasoning_effort_min in EFFORT_ORDER else 1
            max_idx = EFFORT_ORDER.index(reasoning_effort_max) if reasoning_effort_max in EFFORT_ORDER else 3
            target_idx = EFFORT_ORDER.index(target_effort)
            profile_target_idx = max(min_idx, min(max_idx, target_idx))

            for p, mod, m in candidates:
                support = m.reasoning_support.get(mod, "unknown")
                if support == "unsupported":
                    continue
                elif support == "fixed_by_model":
                    valid_reasoning_candidates.append((p, mod, m, "fixed_by_model"))
                elif support == "unknown":
                    # Unknown remains eligible only as uncontrolled/unknown, NOT numeric effort
                    valid_reasoning_candidates.append((p, mod, m, "unknown"))
                elif support in EFFORT_STRS:
                    model_max_idx = EFFORT_STRS.index(support)
                    # If resulting model-supported effort would fall below profile's required minimum, ineligible
                    if model_max_idx < min_idx:
                        continue
                    selected_idx = min(profile_target_idx, model_max_idx)
                    valid_reasoning_candidates.append((p, mod, m, EFFORT_STRS[selected_idx]))
                else:
                    valid_reasoning_candidates.append((p, mod, m, EFFORT_STRS[profile_target_idx]))

            if not valid_reasoning_candidates:
                raise ReasoningControlUnsupported(
                    f"No eligible provider found satisfying adaptive reasoning bounds [{reasoning_effort_min}, {reasoning_effort_max}]."
                )

        elif user_fixed_effort is not None or reasoning_policy == ReasoningPolicy.FIXED:
            eff_val = user_fixed_effort.value if hasattr(user_fixed_effort, "value") else str(user_fixed_effort or ReasoningEffort.MEDIUM.value)
            req_idx = EFFORT_STRS.index(eff_val) if eff_val in EFFORT_STRS else -1
            for p, mod, m in candidates:
                support = m.reasoning_support.get(mod, "unknown")
                if support == "unsupported":
                    continue
                elif support == "fixed_by_model":
                    if eff_val == ReasoningEffort.INSTANT.value:
                        valid_reasoning_candidates.append((p, mod, m, "fixed_by_model"))
                elif support == "unknown":
                    if eff_val == ReasoningEffort.INSTANT.value:
                        valid_reasoning_candidates.append((p, mod, m, "unknown"))
                elif support in EFFORT_STRS:
                    model_max_idx = EFFORT_STRS.index(support)
                    # If requested effort <= model's maximum supported effort:
                    if req_idx != -1 and req_idx <= model_max_idx:
                        valid_reasoning_candidates.append((p, mod, m, eff_val))

            if not valid_reasoning_candidates and eff_val != ReasoningEffort.INSTANT.value:
                raise ReasoningControlUnsupported(f"No eligible provider found satisfying fixed reasoning effort: {eff_val}")

        else:
            # Unconstrained reasoning context: pass all candidates with their natural support
            for p, mod, m in candidates:
                support = m.reasoning_support.get(mod, "unknown")
                if support != "unsupported":
                    effort_tag = None if support == "unknown" else support
                    valid_reasoning_candidates.append((p, mod, m, effort_tag))

        if not valid_reasoning_candidates:
            raise NoEligibleRoute("No eligible models found satisfying reasoning constraints.")

        # 6. Multi-criteria Ranking / Filtering: Cost and Latency
        cost_scores = {"low": 1, "medium": 2, "high": 3}
        latency_scores = {"low": 1, "medium": 2, "high": 3}

        def rank_candidate(item):
            p, mod, meta, effort_selected = item
            c_score = cost_scores.get(meta.cost_class, 2)
            l_score = latency_scores.get(meta.latency_class, 2)
            default_pref = 0 if p == default_provider else 1

            if getattr(context, "cost_preference", None) == "low" and getattr(context, "latency_preference", None) == "low":
                return (c_score, l_score, default_pref)
            elif getattr(context, "cost_preference", None) == "low":
                return (c_score, default_pref)
            elif getattr(context, "latency_preference", None) == "low":
                return (l_score, default_pref)
            else:
                return (default_pref, c_score)

        valid_reasoning_candidates.sort(key=rank_candidate)
        chosen_prov, chosen_model, chosen_meta, chosen_effort = valid_reasoning_candidates[0]

        # Enforce ask_before_cloud (Requirement 10)
        if fallback_policy == FallbackPolicy.ASK_BEFORE_CLOUD and chosen_meta.privacy_status == "cloud":
            default_meta = available_metadata.get(default_provider)
            from_privacy = default_meta.privacy_status if default_meta else "local"
            details = {
                "proposed_provider": chosen_prov,
                "proposed_model": chosen_model,
                "reason": "fallback_to_cloud",
                "from_privacy": from_privacy,
                "to_privacy": chosen_meta.privacy_status,
                "profile_id": getattr(context, "profile_id", None),
            }
            raise RoutingConfirmationRequired(
                f"Cloud provider '{chosen_prov}' ({chosen_model}) selected but policy requires confirmation before cloud execution.",
                details=details,
            )

        # Build descriptive reason code for traceability and milestone compatibility
        reasons = []
        if privacy in (PrivacyPolicy.CONFIDENTIAL, "confidential"):
            reasons.append("confidential_privacy")
        elif privacy in (PrivacyPolicy.LOCAL_ONLY, "local_only"):
            reasons.append("local_only_privacy")
        if getattr(context, "task_type", None):
            reasons.append(context.task_type)
        for cap in req_caps:
            if cap not in reasons:
                reasons.append(cap)
        if getattr(context, "latency_preference", None) == "low":
            reasons.append("low_latency")
        if getattr(context, "cost_preference", None) == "low":
            reasons.append("low_cost")

        reason_code = "_".join(reasons) + "_matched" if reasons else "routing_pipeline_matched"

        return ModelSelection(
            provider_name=chosen_prov,
            model_name=chosen_model,
            reason=reason_code,
            context=context,
            reasoning_effort_selected=chosen_effort,
        )
