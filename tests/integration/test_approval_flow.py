"""Integration tests for approval lifecycle and decision recording."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.approvals.service import ApprovalService
from app.db.models import RunModel, SessionModel


@pytest.mark.asyncio
async def test_approval_lifecycle(test_db_session: AsyncSession):
    session_id = "sess-appr"
    run_id = "run-appr"

    # Setup parent session and run records
    session = SessionModel(id=session_id)
    run = RunModel(id=run_id, session_id=session_id, user_message="write file")
    test_db_session.add(session)
    test_db_session.add(run)
    await test_db_session.commit()

    service = ApprovalService(test_db_session)

    # 1. Create pending approval
    approval = await service.create_approval(
        run_id=run_id,
        session_id=session_id,
        tool_name="write_workspace_file",
        tool_input={"path": "important.txt", "content": "secret data"},
        risk_level="HIGH",
    )
    assert approval.status == "pending"

    # 2. List pending approvals
    pending = await service.get_pending_approvals()
    assert len(pending) == 1
    assert pending[0].id == approval.id

    # 3. Apply decision
    updated = await service.record_decision(
        approval_id=approval.id,
        decision="approved",
        decision_notes="User confirmed write action.",
    )
    assert updated.status == "approved"
    assert updated.decided_at is not None

    # 4. Pending list should now be empty
    pending_now = await service.get_pending_approvals()
    assert len(pending_now) == 0
