"""Pydantic schemas for API request and response DTOs."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# --- Chat Schemas ---
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique UUID of the conversation session")
    message: str = Field(..., min_length=1, description="User query or instruction")
    project_name: Optional[str] = Field(default=None, description="Optional project context scope")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional execution controls / metadata")
    model_override: Optional[str] = Field(default=None, description="Optional provider:model override (e.g. ollama:llama3.2)")


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["completed", "waiting_for_approval", "failed", "cancelled"]
    response: Optional[str] = None
    approval_id: Optional[str] = None
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


# --- Model Discovery Schemas ---
class ModelInfoResponse(BaseModel):
    id: str
    label: str
    capabilities: List[str] = Field(default_factory=list)
    tool_support: Literal["supported", "unsupported", "unknown"] = "unknown"


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

