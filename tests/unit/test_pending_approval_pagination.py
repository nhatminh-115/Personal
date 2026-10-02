"""Pending approval collection reads return stable bounded pages."""

import uuid

import pytest

from app.approvals.service import ApprovalService
from app.db.models import RunModel, SessionModel


@pytest.mark.asyncio
async def test_pending_approvals_page_with_next_cursor(async_client, test_db_session):
    session_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    test_db_session.add(SessionModel(id=session_id, title="Approval pagination", metadata_json={}))
    test_db_session.add(RunModel(
        id=run_id,
        session_id=session_id,
        status="waiting_for_approval",
        user_message="Review a pending action",
    ))
    await test_db_session.commit()

    service = ApprovalService(test_db_session)
    for index in range(3):
        await service.create_approval(
            run_id=run_id,
            session_id=session_id,
            tool_name=f"tool-{index}",
            tool_input={"index": index},
        )

    full = (await async_client.get("/v1/approvals/pending")).json()
    first = await async_client.get("/v1/approvals/pending", params={"page_size": 2})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()] == [item["id"] for item in full[:2]]
    cursor = first.headers.get("X-Next-Cursor")
    assert cursor

    second = await async_client.get(
        "/v1/approvals/pending",
        params={"page_size": 2, "cursor": cursor},
    )
    assert [item["id"] for item in second.json()] == [item["id"] for item in full[2:]]
    assert second.headers.get("X-Next-Cursor") is None


@pytest.mark.asyncio
async def test_pending_approvals_reject_invalid_cursor_and_oversized_page(async_client):
    invalid = await async_client.get("/v1/approvals/pending", params={"cursor": "not-a-cursor"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "Invalid pagination cursor."

    oversized = await async_client.get("/v1/approvals/pending", params={"page_size": 26})
    assert oversized.status_code == 422
