from app.api.routes.runs import _safe_event_payload


def test_context_loaded_exposes_only_valid_memory_privacy_provenance():
    safe = _safe_event_payload("context_loaded", {
        "context_count": 3,
        "history_length": 5,
        "compiled_object_count": 1,
        "memory_privacy_requirement": "local_only",
        "memory_privacy_sources": [
            {"memory_id": "profile-memory-1", "privacy_policy": "local_only"},
            {"memory_id": "project-memory-1", "privacy_policy": "internal"},
            {"memory_id": "bad-policy", "privacy_policy": "secret"},
            {"memory_id": "missing-id"},
            "malformed-source",
        ],
        "memory_text": "private memory content must never appear in traces",
    })

    assert safe == {
        "context_count": 3,
        "history_length": 5,
        "compiled_object_count": 1,
        "memory_privacy_sources": [
            {"memory_id": "profile-memory-1", "privacy_policy": "local_only"},
            {"memory_id": "project-memory-1", "privacy_policy": "internal"},
        ],
    }
