"""Chat request schema bounds align API inputs with persisted workspace identifiers."""

import pytest
from pydantic import ValidationError

from app.api.schemas import ChatRequest, MAX_CHAT_METADATA_BYTES


def _chat_request(**overrides):
    return {
        "session_id": "s" * 36,
        "message": "hello",
        **overrides,
    }


def test_chat_request_accepts_database_sized_scope_identifiers():
    request = ChatRequest.model_validate(_chat_request(project_name="p" * 128, context_object_ids=["o" * 36]))

    assert request.project_name == "p" * 128
    assert request.context_object_ids == ["o" * 36]


def test_chat_request_accepts_explicit_selected_file_text_with_bounds():
    object_id = "o" * 36
    request = ChatRequest.model_validate(_chat_request(
        context_object_ids=[object_id],
        context_attachments=[{"object_id": object_id, "text": "selected text"}],
    ))

    assert request.context_attachments[0].object_id == object_id
    assert request.context_attachments[0].text == "selected text"


@pytest.mark.parametrize("overrides", [
    {"context_attachments": [{"object_id": "o" * 36, "text": "not selected"}]},
    {"context_object_ids": ["o" * 36], "context_attachments": [
        {"object_id": "o" * 36, "text": "first"}, {"object_id": "o" * 36, "text": "duplicate"},
    ]},
    {"context_object_ids": ["o" * 36], "context_attachments": [{"object_id": "o" * 36, "text": "x" * 20_001}]},
    {"context_object_ids": [f"{index:036d}" for index in range(3)], "context_attachments": [
        {"object_id": "0" * 36, "text": "x" * 20_000}, {"object_id": "1" * 36, "text": "x" * 20_000},
        {"object_id": "2" * 36, "text": "x" * 1},
    ]},
])
def test_chat_request_rejects_invalid_or_oversized_file_text(overrides):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(_chat_request(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"session_id": "s" * 37},
        {"project_name": "p" * 129},
        {"context_object_ids": ["o" * 37]},
        {"context_object_ids": [""]},
        {"metadata": {"payload": "x" * MAX_CHAT_METADATA_BYTES}},
        {"metadata": {"zoom": float("nan")}},
    ],
)
def test_chat_request_rejects_invalid_or_oversized_routing_metadata(overrides):
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(_chat_request(**overrides))


@pytest.mark.asyncio
async def test_chat_rejects_overlong_session_id_before_creating_a_session(async_client):
    response = await async_client.post(
        "/v1/chat",
        json={"session_id": "s" * 37, "message": "hello"},
    )

    assert response.status_code == 422
