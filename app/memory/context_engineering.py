"""Deterministic context ranking, budgeting, transformation, and manifest models.

The module deliberately has no model-provider dependency. It consumes source
metadata already collected by AURA and never calls a model while compiling a
context package.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable, Protocol

from pydantic import BaseModel, Field

from app.memory.context_compiler import PRIVACY_REQUIREMENT_ORDER


UNKNOWN_CONTEXT_WINDOW_FALLBACK = 8_192
DEFAULT_OUTPUT_RESERVATION = 1_024
DEFAULT_SAFETY_MARGIN_RATIO = 0.10
DEFAULT_SAFETY_MARGIN_MINIMUM = 128
FRESHNESS_HALF_LIFE_DAYS = 30.0
GRAPH_RELATION_RELEVANCE = 0.75

SCORE_WEIGHTS = {
    "relevance": 0.40,
    "freshness": 0.15,
    "authority": 0.25,
    "utility": 0.20,
}


class ContextPriority(StrEnum):
    EXPLICIT_SELECTION = "explicit_selection"
    USER_AUTHORED_NOTE = "user_authored_note"
    CONTEXT_BRIDGE = "context_bridge"
    REQUIRED_ANCESTRY = "required_ancestry"
    VERIFIED_RESEARCH_EVIDENCE = "verified_research_evidence"
    PROJECT_MEMORY = "project_memory"
    EXTERNAL_RETRIEVED = "external_retrieved"
    OPTIONAL_EXECUTION = "optional_execution"


PRIORITY_ORDER = {priority: index for index, priority in enumerate(ContextPriority)}
SUPPORTED_SOURCE_TYPES = {
    "conversation_turn",
    "conversation_branch",
    "manual_note",
    "context_bridge",
    "context_set",
    "research_paper",
    "research_evidence",
    "project_memory",
    "profile_memory",
    "semantic_memory",
    "episodic_memory",
    "workspace_file",
    "execution_result",
    "external_retrieval",
}


class ContextScoreBreakdown(BaseModel):
    relevance: float | None = None
    freshness: float | None = None
    authority: float | None = None
    utility: float | None = None
    weighted_total: float
    priority_class: ContextPriority


class ContextItem(BaseModel):
    """Canonical candidate record; content remains runtime-only, never trace data."""

    item_id: str
    source_type: str
    source_id: str | None = None
    object_id: str | None = None
    project_id: str | None = None
    scope: str = "project"
    content_reference: str | None = None
    content: str = Field(repr=False)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    authority: float | None = None
    freshness: float | None = None
    relevance: float | None = None
    utility: float | None = None
    privacy_classification: str | None = None
    explicitly_selected: bool = False
    user_authored: bool = False
    required: bool = False
    provenance: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    selected_sections: dict[str, bool | None] | None = None
    allow_extractive_transform: bool = False
    expires_at: datetime | None = None
    pre_exclusion_reason: str | None = None
    estimated_tokens: int = 0
    score: ContextScoreBreakdown | None = None


class ContextBudget(BaseModel):
    model_context_window: int | None = None
    effective_context_window: int
    context_window_source: str
    tokenizer: str
    system_tokens: int
    tool_tokens: int
    user_tokens: int
    conversation_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    available_context_tokens: int
    estimated_context_tokens: int
    remaining_context_tokens: int


class ContextExclusion(BaseModel):
    item_id: str
    reason: str


class ContextTransformationRecord(BaseModel):
    item_id: str
    transformation: str
    original_tokens: int
    final_tokens: int
    provenance: list[str] = Field(default_factory=list)


class ContextManifest(BaseModel):
    version: int = 1
    project_name: str | None = None
    budget: ContextBudget
    candidate_count: int
    included_item_count: int
    excluded_item_count: int
    selected_item_ids: list[str]
    priority_classes: dict[str, list[str]] = Field(default_factory=dict)
    scores: dict[str, ContextScoreBreakdown] = Field(default_factory=dict)
    transformations: list[ContextTransformationRecord] = Field(default_factory=list)
    exclusions: list[ContextExclusion] = Field(default_factory=list)
    included_objects: list[dict[str, object]] = Field(default_factory=list)
    privacy_sources: list[dict[str, str]] = Field(default_factory=list)
    privacy_requirement: str | None = None


class ContextPackage(BaseModel):
    items: list[ContextItem] = Field(default_factory=list)
    rendered_context: list[str] = Field(default_factory=list)
    manifest: ContextManifest


class TokenEstimator(Protocol):
    name: str

    def count(self, text: str) -> int: ...


class ConservativeTokenEstimator:
    """UTF-8 byte estimate used if no compatible tokenizer is installed."""

    name = "utf8-bytes-ceil-div-3"

    def count(self, text: str) -> int:
        return (len(text.encode("utf-8")) + 2) // 3


class TiktokenEstimator:
    def __init__(self, model_name: str) -> None:
        import tiktoken

        self.encoding = tiktoken.encoding_for_model(model_name)
        self.name = f"tiktoken:{self.encoding.name}"

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text))


def create_token_estimator(model_name: str | None) -> TokenEstimator:
    if model_name:
        try:
            return TiktokenEstimator(model_name)
        except (ImportError, KeyError, ValueError):
            pass
    return ConservativeTokenEstimator()


def estimate_tokens(text: str, model_name: str | None = None) -> tuple[int, str]:
    estimator = create_token_estimator(model_name)
    return estimator.count(text), estimator.name


def render_context_item(item: ContextItem) -> str:
    return (
        f"[Context item {item.item_id} | source: {item.source_type} | provenance: {', '.join(item.provenance) or 'direct'}]\n"
        f"{item.content}"
    )


def priority_for(item: ContextItem) -> ContextPriority:
    if item.explicitly_selected:
        return ContextPriority.EXPLICIT_SELECTION
    if item.source_type == "manual_note" and item.user_authored:
        return ContextPriority.USER_AUTHORED_NOTE
    if item.source_type == "context_bridge":
        return ContextPriority.CONTEXT_BRIDGE
    if item.source_type in {"conversation_turn", "conversation_branch"}:
        return ContextPriority.REQUIRED_ANCESTRY
    if item.source_type == "research_evidence":
        return ContextPriority.VERIFIED_RESEARCH_EVIDENCE
    if item.source_type in {"execution_result", "episodic_memory"}:
        return ContextPriority.OPTIONAL_EXECUTION
    if item.source_type == "external_retrieval":
        return ContextPriority.EXTERNAL_RETRIEVED
    return ContextPriority.PROJECT_MEMORY


def _bounded_score(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return min(1.0, max(0.0, float(value)))


def freshness_from_timestamp(updated_at: datetime | None, as_of: datetime) -> float | None:
    if updated_at is None:
        return None
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (as_of - updated_at).total_seconds() / 86_400)
    return math.exp(-math.log(2) * age_days / FRESHNESS_HALF_LIFE_DAYS)


def score_item(item: ContextItem, as_of: datetime | None = None) -> ContextScoreBreakdown:
    """Apply fixed weights; unknown signals use a neutral midpoint, not an inference."""
    evaluated_at = as_of or datetime.now(timezone.utc)
    relevance = _bounded_score(item.relevance)
    freshness = _bounded_score(item.freshness)
    if freshness is None:
        freshness = _bounded_score(freshness_from_timestamp(item.updated_at, evaluated_at))
    authority = _bounded_score(item.authority)
    utility = _bounded_score(item.utility)
    components = {
        "relevance": 0.5 if relevance is None else relevance,
        "freshness": 0.5 if freshness is None else freshness,
        "authority": 0.5 if authority is None else authority,
        "utility": 0.5 if utility is None else utility,
    }
    total = sum(components[key] * SCORE_WEIGHTS[key] for key in SCORE_WEIGHTS)
    return ContextScoreBreakdown(
        relevance=relevance,
        freshness=freshness,
        authority=authority,
        utility=utility,
        weighted_total=round(total, 6),
        priority_class=priority_for(item),
    )


def rank_items(items: list[ContextItem], as_of: datetime | None = None) -> list[ContextItem]:
    scored = [item.model_copy(update={"score": score_item(item, as_of)}) for item in items]
    return sorted(
        scored,
        key=lambda item: (
            PRIORITY_ORDER[item.score.priority_class],
            -item.score.weighted_total,
            item.item_id,
            item.source_id or "",
        ),
    )


class ContextFilterPolicy(BaseModel):
    project_id: str | None = None
    privacy_requirement: str | None = None
    available_capabilities: set[str] = Field(default_factory=set)
    now: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def hard_filter_items(
    items: list[ContextItem], policy: ContextFilterPolicy,
) -> tuple[list[ContextItem], list[ContextExclusion]]:
    """Apply scope, privacy, capability, provenance, expiry, and type gates first."""
    eligible: list[ContextItem] = []
    exclusions: list[ContextExclusion] = []
    for item in items:
        reason = None
        if item.source_type not in SUPPORTED_SOURCE_TYPES:
            reason = "unsupported_type"
        elif item.scope != "global" and policy.project_id and item.project_id and item.project_id != policy.project_id:
            reason = "out_of_scope"
        elif item.scope != "global" and item.project_id and policy.project_id is None:
            reason = "out_of_scope"
        elif item.privacy_classification and item.privacy_classification not in PRIVACY_REQUIREMENT_ORDER:
            reason = "privacy_blocked"
        elif (
            item.privacy_classification
            and policy.privacy_requirement in PRIVACY_REQUIREMENT_ORDER
            and PRIVACY_REQUIREMENT_ORDER[item.privacy_classification] > PRIVACY_REQUIREMENT_ORDER[policy.privacy_requirement]
        ):
            reason = "privacy_blocked"
        elif item.required_capabilities and not set(item.required_capabilities).issubset(policy.available_capabilities):
            reason = "capability_mismatch"
        elif any(not isinstance(reference, str) or not reference.strip() for reference in item.provenance):
            reason = "invalid_provenance"
        else:
            expires_at = item.expires_at
            if expires_at is not None:
                expiry = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
                if expiry <= policy.now:
                    reason = "stale"
        if reason:
            exclusions.append(ContextExclusion(item_id=item.item_id, reason=reason))
        else:
            eligible.append(item)
    return eligible, exclusions


class ContextTransformer(Protocol):
    name: str

    def transform(self, item: ContextItem, max_tokens: int, count_tokens: Callable[[str], int]) -> str | None: ...


class IdentityTransformer:
    name = "identity"

    def transform(self, item: ContextItem, max_tokens: int, count_tokens: Callable[[str], int]) -> str | None:
        return item.content if count_tokens(item.content) <= max_tokens else None


class ExtractiveSentenceTransformer:
    """Select exact source sentences; callers must explicitly allow this per item."""

    name = "extractive_sentences"

    def transform(self, item: ContextItem, max_tokens: int, count_tokens: Callable[[str], int]) -> str | None:
        if item.user_authored or not item.allow_extractive_transform or max_tokens < 1:
            return None
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", item.content) if part.strip()]
        selected: list[str] = []
        for sentence in sentences:
            proposed = " ".join((*selected, sentence))
            if count_tokens(proposed) <= max_tokens:
                selected.append(sentence)
        return " ".join(selected) if selected else None


class ContextHardFilterError(ValueError):
    def __init__(self, item_id: str, reason: str) -> None:
        self.details = {
            "budget_error": "mandatory_context_rejected",
            "item_id": item_id,
            "reason": reason,
            "suggestion": "Review the selected item's scope, privacy classification, provenance, or capability requirements.",
        }
        super().__init__(f"Required context item '{item_id}' failed a hard context policy check ({reason}).")


def allocate_context(
    candidates: list[ContextItem],
    *,
    model_name: str | None,
    model_context_window: int | None,
    fixed_input_tokens: int,
    system_tokens: int,
    tool_tokens: int,
    user_tokens: int,
    conversation_tokens: int,
    reserved_output_tokens: int,
    privacy_requirement: str | None,
    project_id: str | None,
    available_capabilities: set[str] | None = None,
    safety_margin_ratio: float = DEFAULT_SAFETY_MARGIN_RATIO,
    unknown_window_fallback: int = UNKNOWN_CONTEXT_WINDOW_FALLBACK,
    transformer: ContextTransformer | None = None,
    as_of: datetime | None = None,
) -> ContextPackage:
    """Filter, rank, and budget candidates while keeping selected items mandatory."""
    estimator = create_token_estimator(model_name)
    now = as_of or datetime.now(timezone.utc)
    pre_excluded = [
        ContextExclusion(item_id=item.item_id, reason=item.pre_exclusion_reason)
        for item in candidates
        if item.pre_exclusion_reason in {
            "out_of_scope", "privacy_blocked", "capability_mismatch", "duplicate", "lower_priority",
            "stale", "over_budget", "invalid_provenance", "unsupported_type",
        }
    ]
    for item in candidates:
        if (item.explicitly_selected or item.required) and item.pre_exclusion_reason:
            raise ContextHardFilterError(item.item_id, item.pre_exclusion_reason)
    active_candidates = [item for item in candidates if item.pre_exclusion_reason is None]
    eligible, exclusions = hard_filter_items(active_candidates, ContextFilterPolicy(
        project_id=project_id,
        privacy_requirement=privacy_requirement,
        available_capabilities=available_capabilities or set(),
        now=now,
    ))
    excluded_reasons = {row.item_id: row.reason for row in exclusions}
    for item in candidates:
        if (item.explicitly_selected or item.required) and item.item_id in excluded_reasons:
            raise ContextHardFilterError(item.item_id, excluded_reasons[item.item_id])
    ranked = rank_items(eligible, now)
    effective_window = model_context_window or unknown_window_fallback
    window_source = "model_metadata" if model_context_window is not None else "conservative_fallback"
    margin = max(DEFAULT_SAFETY_MARGIN_MINIMUM, math.ceil(effective_window * safety_margin_ratio))
    available = max(0, effective_window - fixed_input_tokens - reserved_output_tokens - margin)
    selected: list[ContextItem] = []
    transforms: list[ContextTransformationRecord] = []
    output_exclusions: list[ContextExclusion] = [*pre_excluded, *exclusions]
    consumed = 0
    active_transformer = transformer or IdentityTransformer()
    seen_content: dict[str, int] = {}

    # Required candidates are reserved first, independent of their ordinary score.
    required = [item for item in ranked if item.explicitly_selected or item.required]
    optional = [item for item in ranked if not (item.explicitly_selected or item.required)]
    for item in (*required, *optional):
        duplicate_index = seen_content.get(item.content) if item.content else None
        if (
            duplicate_index is not None
            and not item.user_authored
            and not item.explicitly_selected
            and not item.required
        ):
            primary = selected[duplicate_index]
            duplicate_reference = item.source_id or item.item_id
            merged_provenance = list(dict.fromkeys([*primary.provenance, duplicate_reference, *item.provenance]))
            selected[duplicate_index] = primary.model_copy(update={"provenance": merged_provenance})
            duplicate_tokens = estimator.count(render_context_item(item))
            output_exclusions.append(ContextExclusion(item_id=item.item_id, reason="duplicate"))
            transforms.append(ContextTransformationRecord(
                item_id=item.item_id,
                transformation="exact_duplicate_merge",
                original_tokens=duplicate_tokens,
                final_tokens=0,
                provenance=[primary.source_id or primary.item_id, *item.provenance],
            ))
            continue
        rendered_item = render_context_item(item)
        header = rendered_item.removesuffix(item.content)
        if item.content == "":
            header = rendered_item
        original_tokens = estimator.count(header + item.content)
        item = item.model_copy(update={"estimated_tokens": original_tokens})
        remaining = max(0, available - consumed)
        header_tokens = estimator.count(header)
        content_budget = max(0, remaining - header_tokens)
        if header_tokens > remaining:
            transformed = None
        elif item.user_authored:
            # Enforce verbatim preservation at the allocator boundary so a
            # future/custom transformer cannot rewrite user-authored material.
            transformed = IdentityTransformer().transform(item, content_budget, estimator.count)
        else:
            transformed = active_transformer.transform(item, content_budget, estimator.count)
        if transformed is None and original_tokens <= remaining:
            # A transformer may refuse a source (for example, user-authored
            # text); preserve it verbatim when the identity form still fits.
            transformed = item.content
        if transformed is None:
            if item.explicitly_selected or item.required:
                raise ContextBudgetExceededError(
                    item_id=item.item_id,
                    required_tokens=original_tokens,
                    available_tokens=remaining,
                    model_context_window=model_context_window,
                    effective_context_window=effective_window,
                )
            reason = "over_budget" if original_tokens > available else "lower_priority"
            output_exclusions.append(ContextExclusion(item_id=item.item_id, reason=reason))
            continue
        final_tokens = estimator.count(header + transformed)
        final_item = item.model_copy(update={"content": transformed, "estimated_tokens": final_tokens})
        selected.append(final_item)
        if item.content and not item.user_authored and not item.explicitly_selected and not item.required:
            seen_content.setdefault(item.content, len(selected) - 1)
        consumed += final_tokens
        if transformed != item.content:
            transforms.append(ContextTransformationRecord(
                item_id=item.item_id,
                transformation=active_transformer.name,
                original_tokens=original_tokens,
                final_tokens=final_tokens,
                provenance=list(item.provenance),
            ))

    selected_ids = {item.item_id for item in selected}
    selected_sorted = sorted(selected, key=lambda item: (
        PRIORITY_ORDER[item.score.priority_class] if item.score else 99,
        -(item.score.weighted_total if item.score else 0),
        item.item_id,
    ))
    selected_by_priority: dict[str, list[str]] = {}
    for item in selected_sorted:
        priority = item.score.priority_class.value if item.score else priority_for(item).value
        selected_by_priority.setdefault(priority, []).append(item.item_id)

    context_budget = ContextBudget(
        model_context_window=model_context_window,
        effective_context_window=effective_window,
        context_window_source=window_source,
        tokenizer=estimator.name,
        system_tokens=system_tokens,
        tool_tokens=tool_tokens,
        user_tokens=user_tokens,
        conversation_tokens=conversation_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=margin,
        available_context_tokens=available,
        estimated_context_tokens=consumed,
        remaining_context_tokens=max(0, available - consumed),
    )
    manifest = ContextManifest(
        project_name=project_id,
        budget=context_budget,
        candidate_count=len(candidates),
        included_item_count=len(selected),
        excluded_item_count=len(output_exclusions),
        selected_item_ids=[item.item_id for item in selected_sorted],
        priority_classes=selected_by_priority,
        scores={item.item_id: item.score for item in ranked if item.score is not None},
        transformations=transforms,
        exclusions=sorted(output_exclusions, key=lambda row: row.item_id),
        included_objects=[
            {
                "item_id": item.item_id,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "object_id": item.object_id,
                "project_id": item.project_id,
                "priority_class": item.score.priority_class.value if item.score else priority_for(item).value,
                "estimated_tokens": item.estimated_tokens,
                "source_object_ids": list(item.provenance),
                "selected_by_user": item.explicitly_selected,
                **({"selected_sections": item.selected_sections} if item.selected_sections is not None else {}),
            }
            for item in selected_sorted
        ],
        privacy_sources=[
            {
                "object_id": item.object_id or item.source_id or item.item_id,
                "privacy_policy": item.privacy_classification,
            }
            for item in selected_sorted
            if item.privacy_classification is not None
        ],
        privacy_requirement=privacy_requirement,
    )
    rendered = [render_context_item(item) for item in selected_sorted]
    return ContextPackage(items=selected_sorted, rendered_context=rendered, manifest=manifest)


class ContextBudgetExceededError(ValueError):
    def __init__(
        self, *, item_id: str, required_tokens: int, available_tokens: int,
        model_context_window: int | None, effective_context_window: int,
    ) -> None:
        self.details = {
            "budget_error": "mandatory_context_overflow",
            "item_id": item_id,
            "required_tokens": required_tokens,
            "available_tokens": available_tokens,
            "model_context_window": model_context_window,
            "effective_context_window": effective_context_window,
            "suggestion": "Choose a model with a larger context window or reduce the explicitly selected context.",
        }
        super().__init__("Explicitly selected context cannot fit within the available model context budget.")
