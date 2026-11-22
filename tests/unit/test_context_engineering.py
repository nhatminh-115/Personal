"""Semantic coverage for deterministic context ranking and allocation."""

from datetime import datetime, timedelta, timezone

import pytest

from app.memory.context_engineering import (
    ContextBudgetExceededError,
    ContextHardFilterError,
    ContextItem,
    ContextPriority,
    ContextFilterPolicy,
    ExtractiveSentenceTransformer,
    allocate_context,
    freshness_from_timestamp,
    hard_filter_items,
    rank_items,
    score_item,
)
from app.orchestrator.nodes import _context_candidates_from_state
from app.core.errors import ContextSelectionError


AS_OF = datetime(2026, 1, 31, tzinfo=timezone.utc)


def item(item_id: str, **overrides) -> ContextItem:
    values = {
        "item_id": item_id,
        "source_type": "external_retrieval",
        "content": f"Reference content for {item_id}.",
        "scope": "global",
    }
    values.update(overrides)
    return ContextItem(**values)


def allocate(candidates, **overrides):
    values = {
        "model_name": None,
        "model_context_window": 4_096,
        "fixed_input_tokens": 128,
        "system_tokens": 20,
        "tool_tokens": 10,
        "user_tokens": 30,
        "conversation_tokens": 20,
        "reserved_output_tokens": 256,
        "privacy_requirement": "internal",
        "project_id": "alpha",
        "as_of": AS_OF,
    }
    values.update(overrides)
    return allocate_context(candidates, **values)


def test_rank_is_deterministic_and_priority_precedes_weighted_score():
    items = [
        item("z-low", relevance=1.0),
        item("b-note", source_type="manual_note", user_authored=True, relevance=0.0),
        item("a-bridge", source_type="context_bridge", relevance=0.0),
        item("a-low", relevance=1.0),
    ]

    first = rank_items(items, AS_OF)
    second = rank_items(list(reversed(items)), AS_OF)

    assert [candidate.item_id for candidate in first] == ["b-note", "a-bridge", "a-low", "z-low"]
    assert [candidate.item_id for candidate in first] == [candidate.item_id for candidate in second]
    assert first[0].score.priority_class == ContextPriority.USER_AUTHORED_NOTE


def test_score_uses_fixed_weights_and_unknown_signals_are_neutral():
    scored = score_item(item(
        "weighted",
        relevance=1.0,
        freshness=0.0,
        authority=0.5,
        utility=0.25,
    ), AS_OF)
    unknown = score_item(item("unknown"), AS_OF)

    assert scored.weighted_total == 0.575
    assert unknown.weighted_total == 0.5
    assert unknown.relevance is None
    assert unknown.authority is None
    assert freshness_from_timestamp(AS_OF - timedelta(days=30), AS_OF) == pytest.approx(0.5)


def test_hard_filters_run_before_ranking_and_report_actionable_reasons():
    candidates = [
        item("wrong-project", project_id="beta", scope="project"),
        item("private", privacy_classification="local_only"),
        item("capability", required_capabilities=["browser"], scope="global"),
        item("stale", expires_at=AS_OF - timedelta(seconds=1)),
        item("bad-provenance", provenance=[""]),
        item("unknown-type", source_type="made_up"),
    ]

    eligible, exclusions = hard_filter_items(candidates, ContextFilterPolicy(
        project_id="alpha",
        privacy_requirement="internal",
        available_capabilities=set(),
        now=AS_OF,
    ))

    assert eligible == []
    assert {row.item_id: row.reason for row in exclusions} == {
        "wrong-project": "out_of_scope",
        "private": "privacy_blocked",
        "capability": "capability_mismatch",
        "stale": "stale",
        "bad-provenance": "invalid_provenance",
        "unknown-type": "unsupported_type",
    }
    assert all(candidate.score is None for candidate in eligible)


def test_optional_context_is_ranked_and_exact_duplicates_keep_provenance():
    candidates = [
        item("lower", relevance=0.4, content="same factual evidence", source_id="source-lower"),
        item("higher", relevance=0.9, content="same factual evidence", source_id="source-higher"),
        item("other", relevance=0.1, content="different evidence", source_id="source-other"),
    ]

    package = allocate(candidates)

    assert [selected.item_id for selected in package.items] == ["higher", "other"]
    assert any(row.item_id == "lower" and row.reason == "duplicate" for row in package.manifest.exclusions)
    assert package.items[0].provenance == ["source-lower"]
    assert any(row.transformation == "exact_duplicate_merge" for row in package.manifest.transformations)
    assert package.manifest.budget.estimated_context_tokens <= package.manifest.budget.available_context_tokens


def test_explicit_context_is_mandatory_and_overflow_returns_structured_error():
    selected = item("explicit", content="x" * 2_000, explicitly_selected=True, required=True)

    with pytest.raises(ContextBudgetExceededError) as error:
        allocate(
            [selected],
            model_context_window=512,
            fixed_input_tokens=256,
            reserved_output_tokens=128,
        )

    assert error.value.details["budget_error"] == "mandatory_context_overflow"
    assert error.value.details["item_id"] == "explicit"
    assert error.value.details["available_tokens"] >= 0
    assert "larger context window" in error.value.details["suggestion"]


def test_explicit_context_with_existing_exclusion_cannot_be_silently_dropped():
    selected = item(
        "explicit-preexcluded",
        explicitly_selected=True,
        pre_exclusion_reason="out_of_scope",
    )

    with pytest.raises(ContextHardFilterError) as error:
        allocate([selected])

    assert error.value.details["budget_error"] == "mandatory_context_rejected"
    assert error.value.details["item_id"] == "explicit-preexcluded"
    assert error.value.details["reason"] == "out_of_scope"


class RewritingTransformer:
    name = "unsafe_rewrite"

    def transform(self, item, max_tokens, count_tokens):
        return "A compressed rewrite."


def test_user_authored_text_is_never_extractive_transformed():
    exact = "First sentence. Second sentence stays exact."
    authored = item(
        "authored",
        source_type="manual_note",
        user_authored=True,
        content=exact,
        allow_extractive_transform=True,
    )

    package = allocate(
        [authored],
        model_context_window=1_024,
        fixed_input_tokens=100,
        reserved_output_tokens=128,
        transformer=RewritingTransformer(),
    )

    assert package.items[0].content == exact
    assert not package.manifest.transformations


def test_malformed_checkpoint_cannot_silently_drop_selected_context():
    with pytest.raises(ContextSelectionError) as error:
        _context_candidates_from_state({
            "context_candidates": [{"explicitly_selected": True, "content": "selected text"}],
        })

    assert error.value.details["budget_error"] == "mandatory_context_rejected"
    assert error.value.details["reason"] == "invalid_provenance"


def test_opted_in_extractive_transform_preserves_source_provenance():
    external = item(
        "external-1",
        source_id="provider-result-7",
        content="Keep this relevant sentence. " + ("Background detail. " * 40),
        allow_extractive_transform=True,
        provenance=["source-paper-9"],
    )

    package = allocate(
        [external],
        model_context_window=1_024,
        fixed_input_tokens=600,
        reserved_output_tokens=128,
        transformer=ExtractiveSentenceTransformer(),
    )

    assert package.items[0].content.startswith("Keep this relevant sentence.")
    record = package.manifest.transformations[0]
    assert record.transformation == "extractive_sentences"
    assert record.original_tokens > record.final_tokens
    assert record.provenance == ["source-paper-9"]


def test_unknown_model_window_is_explicit_and_uses_documented_fallback():
    package = allocate([], model_context_window=None)

    assert package.manifest.budget.model_context_window is None
    assert package.manifest.budget.effective_context_window == 8_192
    assert package.manifest.budget.context_window_source == "conservative_fallback"


def test_manifest_never_contains_context_content():
    secret_text = "private source content that must not enter trace payloads"
    package = allocate([item("private-id", content=secret_text)])
    serialized_manifest = package.manifest.model_dump_json()

    assert secret_text not in serialized_manifest
    assert "private-id" in serialized_manifest


def test_attachment_content_reference_resolves_once_from_checkpoint_state():
    attachment_text = "Only the explicitly selected file text is sent."
    candidate = item(
        "workspace:file-1",
        source_type="workspace_file",
        object_id="file-1",
        explicitly_selected=True,
        content="[Workspace object file-1]\n[Selected file: notes.txt]",
        content_reference="chat-attachment:file-1",
    )
    state = {
        "context_candidates": [candidate.model_dump(mode="json")],
        "context_attachments": [{"object_id": "file-1", "title": "notes.txt", "text": attachment_text}],
        "project_name": "alpha",
    }

    resolved = _context_candidates_from_state(state)

    assert resolved[0].content.endswith(attachment_text)
    assert resolved[0].content_reference == "chat-attachment:file-1"
    assert attachment_text not in state["context_candidates"][0]["content"]
