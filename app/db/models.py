"""SQLAlchemy ORM models for AURA persistence."""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="runs")
    events: Mapped[List["RunEventModel"]] = relationship("RunEventModel", back_populates="run", cascade="all, delete-orphan")
    approvals: Mapped[List["ApprovalModel"]] = relationship("ApprovalModel", back_populates="run", cascade="all, delete-orphan")


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
    embedding: Mapped[Optional[list[float]]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    session: Mapped[Optional["SessionModel"]] = relationship("SessionModel", back_populates="memories")
