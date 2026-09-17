"""Event taxonomy and typed event models for AURA event infrastructure."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from app.db.models import EventStatus, generate_uuid, utc_now


class EventType(str, Enum):
    """Standardized event taxonomy for proactive triggers and subsystem integration."""
    CRON_TICK = "cron.tick"
    TIMER_FIRED = "timer.fired"
    WEBHOOK_RECEIVED = "webhook.received"
    FILE_CHANGED = "file.changed"
    TASK_RESUMED = "task.resumed"
    MEMORY_CONSOLIDATED = "memory.consolidated"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class AURAEvent(BaseModel):
    """Structured, immutable event message."""

    id: str = Field(default_factory=generate_uuid)
    event_type: str = Field(..., description="Categorical event identifier.")
    source: str = Field(default="system", description="Subsystem or entity originating the event.")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Typed arbitrary event data.")
    occurred_at: datetime = Field(default_factory=utc_now, description="UTC timestamp when event occurred.")
    correlation_id: Optional[str] = Field(None, description="Identifier correlating this event to a run/job/session.")
    idempotency_key: Optional[str] = Field(None, description="Unique key for deduplication.")
    status: EventStatus = Field(default=EventStatus.PENDING, description="Outbox processing state.")
    retry_count: int = Field(default=0)
    max_attempts: int = Field(default=3, description="Maximum retry attempts before dead-letter.")
    next_attempt_at: Optional[datetime] = Field(None, description="Earliest execution time for next attempt.")
    error_message: Optional[str] = None
