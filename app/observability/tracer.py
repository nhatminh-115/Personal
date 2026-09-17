"""Persistent run trace and structured event auditing."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger, mask_sensitive_data
from app.db.models import RunEventModel, RunModel


class TraceService:
    """Records audit events into database and outputs structured logs."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_event(
        self,
        run_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> RunEventModel:
        """Persist a run event and emit structured log."""
        safe_payload = mask_sensitive_data(payload or {})

        event = RunEventModel(
            run_id=run_id,
            event_type=event_type,
            payload=safe_payload,
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)

        logger.info(
            f"RunEvent [{event_type}] for run '{run_id}'",
            extra={
                "run_id": run_id,
                "session_id": session_id,
                "event_type": event_type,
                "details": safe_payload,
            },
        )
        return event

    async def get_run_events(self, run_id: str) -> List[RunEventModel]:
        """Fetch all trace events for a given run in chronological order."""
        query = (
            select(RunEventModel)
            .where(RunEventModel.run_id == run_id)
            .order_by(RunEventModel.created_at.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_run(self, run_id: str) -> Optional[RunModel]:
        """Fetch a run by ID."""
        query = select(RunModel).where(RunModel.id == run_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
