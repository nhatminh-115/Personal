"""Approval request bounds protect durable decision and replay data."""

import pytest
from pydantic import ValidationError

from app.api.schemas import (
    MAX_APPROVAL_DECISION_NOTES_CHARS,
    MAX_APPROVAL_EDITED_INPUT_BYTES,
    ApprovalDecisionRequest,
    RoutingConfirmationDecisionRequest,
)


def test_approval_edited_input_accepts_payload_within_bound():
    request = ApprovalDecisionRequest.model_validate({
        "decision": "edited",
        "edited_input": {"content": "x" * (MAX_APPROVAL_EDITED_INPUT_BYTES - 16)},
    })

    assert len(request.edited_input["content"]) == MAX_APPROVAL_EDITED_INPUT_BYTES - 16


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "edited", "edited_input": {"content": "x" * MAX_APPROVAL_EDITED_INPUT_BYTES}},
        {"decision": "edited", "edited_input": {"value": float("nan")}},
        {"decision": "approved", "decision_notes": "n" * (MAX_APPROVAL_DECISION_NOTES_CHARS + 1)},
    ],
)
def test_approval_decision_rejects_oversized_or_non_json_values(payload):
    with pytest.raises(ValidationError):
        ApprovalDecisionRequest.model_validate(payload)


def test_routing_confirmation_decision_notes_are_bounded():
    with pytest.raises(ValidationError):
        RoutingConfirmationDecisionRequest.model_validate({
            "decision": "approved",
            "decision_notes": "n" * (MAX_APPROVAL_DECISION_NOTES_CHARS + 1),
        })
