"""SQLAlchemy ORM models for AURA persistence."""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, JSON, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base


from enum import Enum


class RunStatus(str, Enum):
    """Explicit run lifecycle states."""
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


class SessionModel(Base):
    """Represents a conversation session/thread."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(255), default="New Session")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    messages: Mapped[List["MessageModel"]] = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")
    runs: Mapped[List["RunModel"]] = relationship("RunModel", back_populates="session", cascade="all, delete-orphan")
    approvals: Mapped[List["ApprovalModel"]] = relationship("ApprovalModel", back_populates="session", cascade="all, delete-orphan")
    memories: Mapped[List["MemoryModel"]] = relationship("MemoryModel", back_populates="session", cascade="all, delete-orphan")


class MessageModel(Base):
    """Chronological message history associated with a session."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))  # "user", "assistant", "system", "tool"
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="messages")


class RunModel(Base):
    """An execution run invoked by user message or external trigger."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running")  # "running", "waiting_for_approval", "completed", "failed"
    user_message: Mapped[str] = mapped_column(Text)
    final_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_run_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="runs")
    events: Mapped[List["RunEventModel"]] = relationship("RunEventModel", back_populates="run", cascade="all, delete-orphan")
    approvals: Mapped[List["ApprovalModel"]] = relationship("ApprovalModel", back_populates="run", cascade="all, delete-orphan")
    parent_run: Mapped[Optional["RunModel"]] = relationship("RunModel", remote_side=[id], back_populates="child_runs")
    child_runs: Mapped[List["RunModel"]] = relationship("RunModel", back_populates="parent_run")


class RunEventModel(Base):
    """Granular trace event emitted during a run lifecycle."""

    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunModel"] = relationship("RunModel", back_populates="events")


class ApprovalModel(Base):
    """Human-in-the-loop approval record for high-risk or write actions."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    tool_input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(32), default="HIGH")
    status: Mapped[str] = mapped_column(String(32), default="pending")  # "pending", "approved", "rejected", "edited"
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="approvals")
    run: Mapped["RunModel"] = relationship("RunModel", back_populates="approvals")


class MemoryModel(Base):
    """Durable memory entity (episodic, semantic, profile, project)."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), index=True)  # "working", "episodic", "semantic", "profile", "project"
    key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text)

    # Real pgvector embedding column & model tracking
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1536), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    embedding_dim: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Scoping & Lifecycle
    project_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    supersedes_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)
    superseded_by_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("memories.id", ondelete="SET NULL"), nullable=True)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    session: Mapped[Optional["SessionModel"]] = relationship("SessionModel", back_populates="memories")


class EventStatus(str, Enum):
    """Lifecycle statuses for event outbox processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class JobType(str, Enum):
    """Supported scheduled job types."""
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"


class EventRecordModel(Base):
    """Transactional event log and durable outbox model."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="system")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=EventStatus.PENDING.value, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=utc_now, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_events_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class ScheduledJobModel(Base):
    """Persistent timer and recurring schedule entity."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128))
    job_type: Mapped[str] = mapped_column(String(32), default=JobType.ONE_SHOT.value)
    schedule_expression: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


