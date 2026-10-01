"""Pydantic schemas for API request and response DTOs."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.capabilities.registry import CapabilityProviderMetadata


# --- Chat Schemas ---
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique UUID of the conversation session")
    message: str = Field(..., min_length=1, description="User query or instruction")
    project_name: Optional[str] = Field(default=None, description="Optional project context scope")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional execution controls / metadata")
    model_override: Optional[str] = Field(default=None, description="Optional provider:model override (e.g. ollama:llama3.2)")
    reasoning_override: Optional[Literal["instant", "low", "medium", "high", "max"]] = None
    task_type: Optional[Literal["research", "coding", "writing"]] = Field(
        default=None,
        description="Optional task route selected by the user; omitted for automatic routing.",
    )
    context_object_ids: List[str] = Field(
        default_factory=list,
        max_length=50,
        description="Explicit project workspace objects to compile into this turn's context",
    )


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["completed", "waiting_for_approval", "failed", "cancelled"]
    response: Optional[str] = None
    approval_id: Optional[str] = None
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)


# --- Approval Schemas ---
class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    session_id: str
    tool_call_id: Optional[str] = None
    tool_name: str
    tool_input: Dict[str, Any]
    risk_level: str
    status: str
    decision_notes: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "edited"]
    decision_notes: Optional[str] = None
    edited_input: Optional[Dict[str, Any]] = None


class ApprovalDecisionResponse(BaseModel):
    approval_id: str
    status: str
    run_id: str
    execution_status: str
    final_response: Optional[str] = None


# --- Session & Message Schemas ---
class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    run_id: Optional[str] = None
    context_manifest: Optional[Dict[str, Any]] = None
    routing_provenance: Optional[Dict[str, Any]] = None


class SessionDetailResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse]


# --- Run & Trace Schemas ---
class RunEventResponse(BaseModel):
    id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime


class RunDetailResponse(BaseModel):
    id: str
    session_id: str
    status: str
    user_message: str
    final_response: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    events: List[RunEventResponse]


# --- Session Listing Schema ---
class SessionSummaryResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


# --- Shared Workspace Object Graph ---
class WorkspaceObjectResponse(BaseModel):
    id: str
    project_name: Optional[str] = None
    session_id: Optional[str] = None
    source_message_id: Optional[str] = None
    object_type: str
    created_by: str
    title: str
    content: str
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class WorkspaceObjectCreate(BaseModel):
    id: Optional[UUID] = Field(default=None, description="Stable client object ID used when restoring an undone workspace object")
    object_type: Literal["manual_note", "context_bridge", "context_set", "conversation_branch"]
    title: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=100_000)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    source_object_ids: List[str] = Field(default_factory=list, max_length=100)


class WorkspaceObjectUpdate(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(max_length=100_000)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceNoteWrite(BaseModel):
    title: str = Field(default="", max_length=255)
    body: str = Field(default="", max_length=100_000)
    tags: List[str] = Field(default_factory=list, max_length=32)
    project_names: List[str] = Field(default_factory=list, max_length=64)
    pinned: bool = False


class WorkspaceNoteResponse(BaseModel):
    id: str
    title: str
    body: str
    tags: List[str]
    project_names: List[str]
    pinned: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceEdgeResponse(BaseModel):
    id: str
    project_name: str
    source_object_id: str
    target_object_id: str
    relation_type: str
    edge_family: Literal["semantic", "context", "execution", "provenance"]
    created_by: str
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WorkspaceEdgeCreate(BaseModel):
    source_object_id: str
    target_object_id: str
    relation_type: str = Field(min_length=1, max_length=48)
    edge_family: Literal["semantic", "context", "execution", "provenance"]
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceLayoutWrite(BaseModel):
    layout: Dict[str, Any]
    expected_revision: int = Field(ge=0)


class WorkspaceLayoutResponse(BaseModel):
    project_name: str
    layout: Dict[str, Any] = Field(default_factory=dict)
    revision: int
    updated_at: Optional[datetime] = None


class WorkspaceExecutionEventResponse(BaseModel):
    id: str
    event_type: str
    created_at: datetime
    agent_role: Optional[str] = None
    specialist: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    child_run_id: Optional[str] = None
    status: Optional[str] = None
    success: Optional[bool] = None
    error_category: Optional[str] = None
    risk_level: Optional[str] = None
    step: Optional[int] = None


class WorkspaceExecutionTraceResponse(BaseModel):
    run_id: str
    parent_run_id: Optional[str] = None
    session_id: str
    user_object_id: Optional[str] = None
    response_object_id: Optional[str] = None
    events: List[WorkspaceExecutionEventResponse] = Field(default_factory=list)


class WorkspaceGraphResponse(BaseModel):
    project_name: str
    objects: List[WorkspaceObjectResponse]
    edges: List[WorkspaceEdgeResponse]
    layout: WorkspaceLayoutResponse
    execution_traces: List[WorkspaceExecutionTraceResponse] = Field(default_factory=list)


class CapabilityProvidersResponse(BaseModel):
    providers: List[CapabilityProviderMetadata] = Field(default_factory=list)


class WorkspaceSessionResponse(BaseModel):
    session_id: str
    project_name: str


# --- Model Discovery Schemas ---
class ModelInfoResponse(BaseModel):
    id: str
    label: str
    capabilities: List[str] = Field(default_factory=list)
    tool_support: Literal["supported", "unsupported", "unknown"] = "unknown"
    context_window: Optional[int] = None
    reasoning_support: Literal["instant", "low", "medium", "high", "max", "fixed_by_model", "unsupported", "unknown"] = "unknown"
    vision_support: Optional[bool] = None
    structured_output_support: Optional[bool] = None


class ProviderInfoResponse(BaseModel):
    id: str
    label: str
    kind: Literal["local", "cloud"]
    available: bool
    base_url: str
    models: List[ModelInfoResponse] = Field(default_factory=list)
    privacy_status: Literal["local", "cloud", "airgap"] = "local"


class ModelCatalogResponse(BaseModel):
    providers: List[ProviderInfoResponse]


class ModelProbeRequest(BaseModel):
    provider_id: str
    model_id: str


class ModelProbeResponse(BaseModel):
    provider_id: str
    model_id: str
    tool_support: Literal["supported", "unsupported", "unknown"]
    details: str


# --- Memory Inspector Schema ---
class MemoryItemResponse(BaseModel):
    id: str
    session_id: Optional[str] = None
    memory_type: str
    project_name: Optional[str] = None
    key: str
    content: str
    confidence: float
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime


# --- Research Inspector Schema ---
class ResearchInspectorResponse(BaseModel):
    run_id: str
    child_run_id: Optional[str] = None
    goal: Optional[Dict[str, Any]] = None
    queries: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    inspected_source_ids: List[str] = Field(default_factory=list)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "unknown"

