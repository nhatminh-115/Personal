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
    WAITING_FOR_ROUTING_CONFIRMATION = "waiting_for_routing_confirmation"
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
    project_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    routing_profile_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("routing_profiles.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    messages: Mapped[List["MessageModel"]] = relationship("MessageModel", back_populates="session", cascade="all, delete-orphan")
    runs: Mapped[List["RunModel"]] = relationship("RunModel", back_populates="session", cascade="all, delete-orphan")
    approvals: Mapped[List["ApprovalModel"]] = relationship("ApprovalModel", back_populates="session", cascade="all, delete-orphan")
    memories: Mapped[List["MemoryModel"]] = relationship("MemoryModel", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sessions_updated_id", "updated_at", "id"),
        Index("ix_sessions_project_updated_id", "project_name", "updated_at", "id"),
    )


class MessageModel(Base):
    """Chronological message history associated with a session."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32))  # "user", "assistant", "system", "tool"
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_session_created_id", "session_id", "created_at", "id"),
    )


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
    routing_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    session: Mapped["SessionModel"] = relationship("SessionModel", back_populates="runs")
    events: Mapped[List["RunEventModel"]] = relationship("RunEventModel", back_populates="run", cascade="all, delete-orphan")
    approvals: Mapped[List["ApprovalModel"]] = relationship("ApprovalModel", back_populates="run", cascade="all, delete-orphan")
    parent_run: Mapped[Optional["RunModel"]] = relationship("RunModel", remote_side=[id], back_populates="child_runs")
    child_runs: Mapped[List["RunModel"]] = relationship("RunModel", back_populates="parent_run")

    __table_args__ = (
        Index("ix_runs_session_created_id", "session_id", "created_at", "id"),
    )


class RunEventModel(Base):
    """Granular trace event emitted during a run lifecycle."""

    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunModel"] = relationship("RunModel", back_populates="events")

    __table_args__ = (
        Index("ix_run_events_run_created_id", "run_id", "created_at", "id"),
    )


class RoutingConfirmationModel(Base):
    """Durable, policy-specific confirmation before a proposed cloud model can run."""

    __tablename__ = "routing_confirmations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    root_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    execution_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    proposed_provider: Mapped[str] = mapped_column(String(128))
    proposed_model: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_routing_confirmations_status_created_id", "status", created_at.desc(), id.desc()),
        Index(
            "ix_routing_confirmations_status_session_created_id",
            "status", "session_id", created_at.desc(), id.desc(),
        ),
    )


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

    __table_args__ = (
        Index("ix_approvals_status_created_id", "status", "created_at", "id"),
    )


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

    __table_args__ = (
        Index("ix_memories_created_id", "created_at", "id"),
        Index("ix_memories_project_created_id", "project_name", "created_at", "id"),
        Index("ix_memories_session_created_id", "session_id", "created_at", "id"),
    )


class EventStatus(str, Enum):
    """Lifecycle statuses for event outbox processing."""
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    CANCELLED = "cancelled"
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
        Index("ix_events_correlation_occurred_id", "correlation_id", "occurred_at", "id"),
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

    __table_args__ = (
        Index("ix_scheduled_jobs_created_id", created_at.desc(), id.asc()),
    )


class DelegationModel(Base):
    """Tracks durable delegation lifecycle between Root Orchestrator and Specialist runs."""

    __tablename__ = "delegations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    parent_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    parent_tool_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    child_run_id: Mapped[str] = mapped_column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    specialist_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="running")
    pending_approval_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index(
            "uq_delegations_parent_call",
            "parent_run_id",
            "parent_tool_call_id",
            unique=True,
            postgresql_where=text("parent_tool_call_id IS NOT NULL"),
            sqlite_where=text("parent_tool_call_id IS NOT NULL"),
        ),
    )


class RoutingProfileModel(Base):
    """Persisted model routing and reasoning policy profile."""

    __tablename__ = "routing_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    global_privacy_policy: Mapped[str] = mapped_column(String(32), default="public")
    global_fallback_policy: Mapped[str] = mapped_column(String(32), default="cloud_allowed")
    cost_preference: Mapped[str] = mapped_column(String(32), default="normal")
    latency_preference: Mapped[str] = mapped_column(String(32), default="normal")
    routes_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index(
            "uq_routing_profiles_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default IS TRUE"),
            sqlite_where=text("is_default = 1"),
        ),
    )


class ProjectRoutingAssignmentModel(Base):
    """Assigns a RoutingProfile to a specific project_name namespace."""
    
    __tablename__ = "project_routing_assignments"
    
    project_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    routing_profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("routing_profiles.id", ondelete="CASCADE"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkspaceProjectModel(Base):
    """User-created project directory entries; built-in demo projects remain client-side."""

    __tablename__ = "workspace_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    name_key: Mapped[str] = mapped_column(String(128), unique=True)
    subtitle: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_workspace_projects_created_id", "created_at", "id"),
        Index("ix_workspace_projects_archived_created_id", "archived_at", "created_at", "id"),
    )


class WorkspaceObjectModel(Base):
    """A durable typed object; null project_name denotes personal workspace scope."""

    __tablename__ = "workspace_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True, index=True)
    source_message_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, unique=True, index=True)
    object_type: Mapped[str] = mapped_column(String(48), index=True)
    created_by: Mapped[str] = mapped_column(String(32), default="user")
    title: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_workspace_objects_project_created_id", "project_name", "created_at", "id"),
        Index(
            "ix_workspace_objects_personal_updated_id",
            "project_name", "object_type", "created_by", updated_at.desc(), id.asc(),
        ),
        Index(
            "ix_workspace_objects_personal_created_id",
            "project_name", "object_type", "created_by", created_at.desc(), id.asc(),
        ),
        Index(
            "ix_workspace_objects_personal_card_created_id",
            "project_name", "object_type", "created_by", created_at, id,
        ),
    )


class WorkspaceObjectProjectLinkModel(Base):
    """Expose one personal workspace object in a project's graph and context."""

    __tablename__ = "workspace_object_project_links"

    object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace_objects.id", ondelete="CASCADE"), primary_key=True
    )
    project_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (Index("ix_workspace_object_project_links_project", "project_name"),)


class WorkspaceEdgeModel(Base):
    """A typed relationship between workspace objects."""

    __tablename__ = "workspace_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_name: Mapped[str] = mapped_column(String(128), index=True)
    source_object_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace_objects.id", ondelete="CASCADE"), index=True)
    target_object_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace_objects.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(48))
    edge_family: Mapped[str] = mapped_column(String(24), index=True)
    created_by: Mapped[str] = mapped_column(String(32), default="user")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("ix_workspace_edges_project_family", "project_name", "edge_family"),
        Index("ix_workspace_edges_project_created_id", "project_name", "created_at", "id"),
    )


class WorkspaceLayoutModel(Base):
    """Per-project spatial state for the Board projection."""

    __tablename__ = "workspace_layouts"

    project_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    layout_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
