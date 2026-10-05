"""Pydantic schemas for API request and response DTOs."""

import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator
from app.capabilities.registry import CapabilityProviderMetadata
from app.events.automation_schedule import AutomationSchedule

MAX_CHAT_METADATA_BYTES = 64 * 1024
MAX_APPROVAL_EDITED_INPUT_BYTES = 2 * 1024 * 1024
MAX_APPROVAL_DECISION_NOTES_CHARS = 4_000
MAX_WORKSPACE_METADATA_BYTES = 64 * 1024
MAX_WORKSPACE_LAYOUT_BYTES = 2 * 1024 * 1024
MAX_CHAT_ATTACHMENT_CHARS = 20_000
MAX_CHAT_ATTACHMENT_TOTAL_CHARS = 40_000


def _validate_json_size(value: Dict[str, Any], max_bytes: int, field_name: str) -> Dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError(f"{field_name} must contain finite JSON values.") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"{field_name} must be {max_bytes} bytes or fewer when serialized as JSON.")
    return value


# --- Chat Schemas ---
class ChatContextAttachment(BaseModel):
    object_id: str = Field(..., min_length=1, max_length=36)
    text: str = Field(..., min_length=1, max_length=MAX_CHAT_ATTACHMENT_CHARS)

    model_config = {"extra": "forbid"}


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=36, description="Unique UUID of the conversation session")
    message: str = Field(..., min_length=1, description="User query or instruction")
    project_name: Optional[str] = Field(default=None, max_length=128, description="Optional project context scope")
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
    context_attachments: List[ChatContextAttachment] = Field(default_factory=list, max_length=5)

    @field_validator("metadata")
    @classmethod
    def validate_metadata_size(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        return _validate_json_size(value, MAX_CHAT_METADATA_BYTES, "metadata")

    @field_validator("context_object_ids")
    @classmethod
    def validate_context_object_ids(cls, value: List[str]) -> List[str]:
        if any(not object_id or len(object_id) > 36 for object_id in value):
            raise ValueError("context_object_ids must contain non-empty object IDs of 36 characters or fewer.")
        return value

    @model_validator(mode="after")
    def validate_context_attachments(self) -> "ChatRequest":
        attachment_ids = [attachment.object_id for attachment in self.context_attachments]
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError("context_attachments must not contain duplicate object IDs.")
        if any(object_id not in self.context_object_ids for object_id in attachment_ids):
            raise ValueError("Each context attachment must also be selected in context_object_ids.")
        total_chars = sum(len(attachment.text) for attachment in self.context_attachments)
        if total_chars > MAX_CHAT_ATTACHMENT_TOTAL_CHARS:
            raise ValueError(
                f"context_attachments must contain {MAX_CHAT_ATTACHMENT_TOTAL_CHARS} characters or fewer in total."
            )
        return self


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["completed", "waiting_for_approval", "waiting_for_routing_confirmation", "failed", "cancelled"]
    response: Optional[str] = None
    approval_id: Optional[str] = None
    routing_confirmation_id: Optional[str] = None
    proposed_provider: Optional[str] = None
    proposed_model: Optional[str] = None
    user_message_id: Optional[str] = None
    assistant_message_id: Optional[str] = None
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)


# --- Routing Confirmation Schemas ---
class RoutingConfirmationResponse(BaseModel):
    id: str
    root_run_id: str
    execution_run_id: str
    session_id: str
    proposed_provider: str
    proposed_model: str
    status: Literal["pending", "approved", "rejected"]
    decision_notes: Optional[str] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class RoutingConfirmationDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    decision_notes: Optional[str] = Field(default=None, max_length=MAX_APPROVAL_DECISION_NOTES_CHARS)


class RoutingConfirmationDecisionResponse(BaseModel):
    confirmation_id: str
    status: Literal["approved", "rejected"]
    run_id: str
    execution_status: str
    final_response: Optional[str] = None
    next_routing_confirmation_id: Optional[str] = None
    approval_id: Optional[str] = None


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
    decision_notes: Optional[str] = Field(default=None, max_length=MAX_APPROVAL_DECISION_NOTES_CHARS)
    edited_input: Optional[Dict[str, Any]] = None

    @field_validator("edited_input")
    @classmethod
    def validate_edited_input_size(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        return _validate_json_size(value, MAX_APPROVAL_EDITED_INPUT_BYTES, "edited_input")


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
    project_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List[MessageResponse]
    messages_next_cursor: Optional[str] = None


class SessionExecutionStateResponse(BaseModel):
    session_id: str
    run_id: Optional[str] = None
    run_status: Optional[str] = None
    approval: Optional[ApprovalResponse] = None


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
    project_name: Optional[str] = None
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
    revision: int
    created_at: datetime
    updated_at: datetime


class WorkspaceObjectCreate(BaseModel):
    id: Optional[UUID] = Field(default=None, description="Stable client object ID used when restoring an undone workspace object")
    object_type: Literal["manual_note", "context_bridge", "context_set", "conversation_branch"]
    title: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=100_000)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    source_object_ids: List[str] = Field(default_factory=list, max_length=100)

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _validate_json_size(value, MAX_WORKSPACE_METADATA_BYTES, "metadata_json")


class WorkspaceObjectUpdate(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(max_length=100_000)
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    expected_revision: int = Field(ge=1)

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _validate_json_size(value, MAX_WORKSPACE_METADATA_BYTES, "metadata_json")


class WorkspaceNoteWrite(BaseModel):
    title: str = Field(default="", max_length=255)
    body: str = Field(default="", max_length=100_000)
    tags: List[str] = Field(default_factory=list, max_length=32)
    project_names: List[str] = Field(default_factory=list, max_length=64)
    pinned: bool = False
    privacy_policy: Optional[Literal["public", "internal", "confidential", "local_only"]] = None
    expected_revision: Optional[int] = Field(default=None, ge=1)


class WorkspaceNoteResponse(BaseModel):
    id: str
    title: str
    body: str
    tags: List[str]
    project_names: List[str]
    pinned: bool
    privacy_policy: Optional[str] = None
    revision: int
    created_at: datetime
    updated_at: datetime


class StudySessionWrite(BaseModel):
    track_id: str = Field(min_length=1, max_length=128)
    track_title: str = Field(min_length=1, max_length=255)
    material_id: Optional[str] = Field(default=None, max_length=36)
    material_project_name: Optional[str] = Field(default=None, max_length=128)


class StudyReflectionWrite(BaseModel):
    reflection: str = Field(default="", max_length=12_000)
    expected_revision: Optional[int] = Field(default=None, ge=1)


class StudyCardWrite(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    answer: str = Field(min_length=1, max_length=8_000)
    expected_revision: Optional[int] = Field(default=None, ge=1)


class StudyCardReviewWrite(BaseModel):
    rating: Literal["again", "remembered", "easy"]
    expected_revision: int = Field(ge=1)


class StudyCardResponse(BaseModel):
    id: str
    session_id: str
    question: str
    answer: str
    created_at: datetime
    updated_at: datetime
    review_count: int = 0
    reviewed_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None
    revision: int = 1


class StudySessionResponse(BaseModel):
    id: str
    track_id: str
    track_title: str
    material_id: Optional[str] = None
    material_project_name: Optional[str] = None
    status: Literal["in_progress", "completed"]
    reflection: str = ""
    started_at: datetime
    completed_at: Optional[datetime] = None
    revision: int = 1


class WorkspaceLibraryReferenceWrite(BaseModel):
    id: Optional[UUID] = None
    name: str = Field(min_length=1, max_length=255)
    kind: Literal["HTML", "PDF", "DOCX", "XLSX", "PPTX", "EPUB", "MD", "CSV", "TXT", "JSON", "IMAGE", "FILE"]
    collection: Literal["Study", "Books", "Research", "Reference"]
    detail: str = Field(default="", max_length=500)
    tags: List[str] = Field(default_factory=list, max_length=32)
    project_names: List[str] = Field(default_factory=list, max_length=64)
    size: Optional[int] = Field(default=None, ge=0)
    mime_type: Optional[str] = Field(default=None, max_length=255)
    expected_revision: Optional[int] = Field(default=None, ge=1)


class WorkspaceLibraryReferenceResponse(BaseModel):
    id: str
    name: str
    kind: str
    collection: str
    detail: str
    tags: List[str]
    project_names: List[str]
    size: Optional[int] = None
    mime_type: Optional[str] = None
    revision: int
    created_at: datetime
    updated_at: datetime


class WorkspaceProjectWrite(BaseModel):
    id: Optional[UUID] = None
    name: str = Field(min_length=1, max_length=128)
    subtitle: str = Field(default="", max_length=255)


class WorkspaceProjectResponse(BaseModel):
    id: str
    name: str
    subtitle: str
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None


class WorkspaceSummaryResponse(BaseModel):
    note_count: int
    library_count: int
    linked_library_count: int
    project_name: Optional[str] = None
    project_note_count: int = 0
    project_library_count: int = 0


class WorkspaceSearchResult(BaseModel):
    object_id: str
    object_type: str
    title: str
    excerpt: str
    project_name: Optional[str] = None
    created_by: str
    verification_status: Optional[str] = None
    related_object_id: Optional[str] = None
    updated_at: datetime


class AutomationWrite(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    instruction: str = Field(min_length=1, max_length=20_000)
    scope: Literal["global", "project"] = "global"
    project_name: Optional[str] = Field(default=None, max_length=128)
    interval_seconds: int = Field(default=86_400, ge=60, le=31_536_000)
    schedule: AutomationSchedule = Field(default_factory=AutomationSchedule)
    webhook_enabled: bool = False


class AutomationEditWrite(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    instruction: str = Field(min_length=1, max_length=20_000)
    interval_seconds: int = Field(default=86_400, ge=60, le=31_536_000)
    schedule: Optional[AutomationSchedule] = None
    webhook_enabled: Optional[bool] = None
    expected_revision: int = Field(ge=1)


class AutomationRevisionWrite(BaseModel):
    expected_revision: int = Field(ge=1)


class AutomationDuplicateWrite(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)


class AutomationExecutionResponse(BaseModel):
    event_id: str
    run_id: str
    queued_at: datetime
    status: str
    retry_count: int = 0
    trigger_type: Literal["schedule", "manual", "webhook", "retry"] = "manual"
    retry_of_event_id: Optional[str] = None


class AutomationResponse(BaseModel):
    id: str
    revision: int = 1
    name: str
    description: str
    instruction: str
    enabled: bool
    archived: bool = False
    scope: Literal["global", "project"]
    project_name: Optional[str] = None
    interval_seconds: int
    schedule: AutomationSchedule = Field(default_factory=AutomationSchedule)
    webhook_enabled: bool = False
    webhook_path: Optional[str] = None
    webhook_secret: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime
    latest_execution: Optional[AutomationExecutionResponse] = None


class AutomationRunResponse(BaseModel):
    event_id: str
    status: Literal["queued"] = "queued"


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
    edge_family: Literal["semantic", "context"]
    metadata_json: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _validate_json_size(value, MAX_WORKSPACE_METADATA_BYTES, "metadata_json")


class WorkspaceContextPreviewRequest(BaseModel):
    selected_object_ids: List[str] = Field(min_length=1, max_length=50)


class WorkspaceContextPreviewObject(BaseModel):
    object_id: str
    object_type: str
    selected_by_user: bool = False
    source_object_ids: List[str] = Field(default_factory=list)
    selected_sections: Dict[str, Optional[bool]] | None = None


class WorkspaceContextPreviewResponse(BaseModel):
    project_name: str
    objects: List[WorkspaceContextPreviewObject] = Field(default_factory=list)
    estimated_tokens: int = 0
    prompt_text: str = ""
    privacy_requirement: Optional[str] = None
    privacy_sources: List[Dict[str, str]] = Field(default_factory=list)
    required_capabilities: List[str] = Field(default_factory=list)
    available_capabilities: List[str] = Field(default_factory=list)
    missing_capabilities: List[str] = Field(default_factory=list)
    requires_tools: bool = False
    requires_vision: bool = False
    requires_structured_output: bool = False
    requires_long_context: bool = False


class WorkspaceEdgeBatchDelete(BaseModel):
    edge_ids: List[str] = Field(min_length=1, max_length=200)


class WorkspaceEdgeRestoreItem(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    source_object_id: str = Field(min_length=1, max_length=36)
    target_object_id: str = Field(min_length=1, max_length=36)
    relation_type: str = Field(min_length=1, max_length=48)
    edge_family: Literal["semantic", "context"]
    metadata_json: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata_json")
    @classmethod
    def validate_metadata_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _validate_json_size(value, MAX_WORKSPACE_METADATA_BYTES, "metadata_json")


class WorkspaceEdgeBatchRestore(BaseModel):
    edges: List[WorkspaceEdgeRestoreItem] = Field(min_length=1, max_length=200)


class WorkspaceLayoutWrite(BaseModel):
    layout: Dict[str, Any]
    expected_revision: int = Field(ge=0)

    @field_validator("layout")
    @classmethod
    def validate_layout_size(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return _validate_json_size(value, MAX_WORKSPACE_LAYOUT_BYTES, "layout")


class WorkspaceLayoutResponse(BaseModel):
    project_name: str
    layout: Dict[str, Any] = Field(default_factory=dict)
    revision: int
    updated_at: Optional[datetime] = None


class WorkspaceContextManifestItemResponse(BaseModel):
    object_id: str
    object_type: str
    selected_by_user: bool = False
    source_object_ids: List[str] = Field(default_factory=list)
    selected_sections: Optional[Dict[str, Optional[bool]]] = None


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
    error_code: Optional[str] = None
    failed_providers: List[str] = Field(default_factory=list)
    risk_level: Optional[str] = None
    step: Optional[int] = None
    task_type: Optional[str] = None
    profile_id: Optional[str] = None
    profile_version: Optional[int] = None
    winning_scope: Optional[str] = None
    privacy: Optional[str] = None
    fallback_policy: Optional[str] = None
    selection_reason: Optional[str] = None
    reasoning_policy: Optional[str] = None
    reasoning_bounds: Optional[Dict[str, Optional[str]]] = None
    selected_effort: Optional[str] = None
    primary_provider: Optional[str] = None
    selected_provider: Optional[str] = None
    candidate_model: Optional[str] = None
    privacy_boundary: Optional[str] = None
    error_type: Optional[str] = None
    proposed_provider: Optional[str] = None
    proposed_model: Optional[str] = None
    trigger_event_id: Optional[str] = None
    automation_id: Optional[str] = None
    automation_name: Optional[str] = None
    context_objects: List[WorkspaceContextManifestItemResponse] = Field(default_factory=list)
    context_estimated_tokens: Optional[int] = None
    context_privacy_requirement: Optional[str] = None


class WorkspaceExecutionTraceResponse(BaseModel):
    run_id: str
    parent_run_id: Optional[str] = None
    session_id: str
    user_object_id: Optional[str] = None
    response_object_id: Optional[str] = None
    events: List[WorkspaceExecutionEventResponse] = Field(default_factory=list)


class WorkspaceExecutionHistoryResponse(BaseModel):
    execution_traces: List[WorkspaceExecutionTraceResponse] = Field(default_factory=list)
    execution_history_truncated: bool = False
    execution_next_cursor: Optional[str] = None


class WorkspaceGraphResponse(BaseModel):
    project_name: str
    objects: List[WorkspaceObjectResponse]
    edges: List[WorkspaceEdgeResponse]
    layout: WorkspaceLayoutResponse
    objects_next_cursor: Optional[str] = None
    edges_next_cursor: Optional[str] = None
    execution_traces: List[WorkspaceExecutionTraceResponse] = Field(default_factory=list)
    execution_history_truncated: bool = False
    execution_next_cursor: Optional[str] = None


class CapabilityProviderResponse(CapabilityProviderMetadata):
    capability_tools: Dict[str, List[str]] = Field(default_factory=dict, description="Bindings verified against available AURA tools")
    declared_capability_tools: Dict[str, List[str]] = Field(default_factory=dict, description="Configured bindings not necessarily discovered or usable")


class CapabilityProvidersResponse(BaseModel):
    providers: List[CapabilityProviderResponse] = Field(default_factory=list)


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
    is_active: bool = True
    supersedes_id: Optional[str] = None
    superseded_by_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime


class MemoryActivationUpdate(BaseModel):
    is_active: bool


class ProjectMemoryContentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=12_000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Memory content must not be blank.")
        return cleaned


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

