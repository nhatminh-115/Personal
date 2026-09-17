"""Service for managing human-in-the-loop approval workflows."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApprovalNotFoundError
from app.core.logging import logger
from app.db.models import ApprovalModel


class ApprovalService:
    """Handles lifecycle of pending, approved, rejected, or edited tool actions."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_approval(
        self,
        run_id: str,
        session_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        risk_level: str = "HIGH",
    ) -> ApprovalModel:
        """Create a new pending approval record."""
        approval = ApprovalModel(
            run_id=run_id,
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            risk_level=risk_level,
            status="pending",
        )
        self.db.add(approval)
        await self.db.commit()
        await self.db.refresh(approval)
        logger.info(
            f"Created pending approval '{approval.id}' for tool '{tool_name}'",
            extra={"run_id": run_id, "session_id": session_id, "approval_id": approval.id},
        )
        return approval

    async def get_pending_approvals(self) -> List[ApprovalModel]:
        """Fetch all approvals currently in 'pending' status."""
        query = (
            select(ApprovalModel)
            .where(ApprovalModel.status == "pending")
            .order_by(ApprovalModel.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_approval_by_run(self, run_id: str) -> Optional[ApprovalModel]:
        """Fetch approval associated with a run ID."""
        query = (
            select(ApprovalModel)
            .where(ApprovalModel.run_id == run_id)
            .order_by(ApprovalModel.created_at.desc())
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_approval(self, approval_id: str) -> ApprovalModel:
        """Fetch an approval by ID."""
        query = select(ApprovalModel).where(ApprovalModel.id == approval_id)
        result = await self.db.execute(query)
        approval = result.scalar_one_or_none()
        if not approval:
            raise ApprovalNotFoundError(f"Approval with ID '{approval_id}' not found.")
        return approval

    async def record_decision(
        self,
        approval_id: str,
        decision: str,  # "approved", "rejected", "edited"
        decision_notes: Optional[str] = None,
        edited_input: Optional[Dict[str, Any]] = None,
    ) -> ApprovalModel:
        """Apply user decision to an approval record."""
        approval = await self.get_approval(approval_id)

        approval.status = decision.lower()
        approval.decision_notes = decision_notes
        if edited_input is not None and decision.lower() == "edited":
            approval.tool_input = edited_input
        approval.decided_at = datetime.now(timezone.utc)

        await self.db.commit()
        await self.db.refresh(approval)
        logger.info(
            f"Approval '{approval_id}' updated to status '{decision}'",
            extra={"approval_id": approval_id, "status": decision},
        )
        return approval
