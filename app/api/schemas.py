"""Pydantic schemas for API request and response DTOs."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# --- Chat Schemas ---
class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Unique UUID of the conversation session")
    message: str = Field(..., min_length=1, description="User query or instruction")


class ChatResponse(BaseModel):
    run_id: str
    session_id: str
    status: Literal["completed", "waiting_for_approval", "failed"]
    response: Optional[str] = None
    approval_id: Optional[str] = None
    tool_results: List[Dict[str, Any]] = Field(default_factory=list)


# --- Approval Schemas ---
class ApprovalResponse(BaseModel):
    id: str
    run_id: str
    session_id: str
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
