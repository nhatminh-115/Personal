"""Persistent run trace and structured event auditing."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger, mask_sensitive_data
from app.db.models import RunEventModel, RunModel
from app.observability.payloads import sanitize_trace_payload


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
        sanitized_payload = sanitize_trace_payload(event_type, payload or {})
        safe_payload = mask_sensitive_data(sanitized_payload)
        if event_type == "context_package_compiled":
            # The event sanitizer has already allowlisted these operational
            # counters and estimator labels. The generic secret masker treats
            # every key containing "token" as secret, which would otherwise
            # erase the budget data the Context Inspector needs.
            safe_budget = safe_payload.get("budget")
            sanitized_budget = sanitized_payload.get("budget")
            if isinstance(safe_budget, dict) and isinstance(sanitized_budget, dict):
                for field in (
                    "model_context_window", "effective_context_window", "system_tokens", "tool_tokens",
                    "user_tokens", "conversation_tokens", "reserved_output_tokens", "safety_margin_tokens",
                    "available_context_tokens", "estimated_context_tokens", "remaining_context_tokens",
                    "context_window_source", "tokenizer",
                ):
                    if field in sanitized_budget:
                        safe_budget[field] = sanitized_budget[field]
            sanitized_included = sanitized_payload.get("included_objects")
            safe_included = safe_payload.get("included_objects")
            if isinstance(sanitized_included, list) and isinstance(safe_included, list):
                token_counts = {
                    row.get("item_id"): row.get("estimated_tokens")
                    for row in sanitized_included
                    if isinstance(row, dict) and isinstance(row.get("item_id"), str)
                    and isinstance(row.get("estimated_tokens"), int)
                }
                for row in safe_included:
                    if isinstance(row, dict) and row.get("item_id") in token_counts:
                        row["estimated_tokens"] = token_counts[row["item_id"]]
            sanitized_transforms = sanitized_payload.get("transformations")
            safe_transforms = safe_payload.get("transformations")
            if isinstance(sanitized_transforms, list) and isinstance(safe_transforms, list):
                transform_counts = {
                    row.get("item_id"): (row.get("original_tokens"), row.get("final_tokens"))
                    for row in sanitized_transforms
                    if isinstance(row, dict) and isinstance(row.get("item_id"), str)
                    and isinstance(row.get("original_tokens"), int)
                    and isinstance(row.get("final_tokens"), int)
                }
                for row in safe_transforms:
                    if isinstance(row, dict) and row.get("item_id") in transform_counts:
                        row["original_tokens"], row["final_tokens"] = transform_counts[row["item_id"]]

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
            .order_by(RunEventModel.created_at.asc(), RunEventModel.id.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_run(self, run_id: str) -> Optional[RunModel]:
        """Fetch a run by ID."""
        query = select(RunModel).where(RunModel.id == run_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
