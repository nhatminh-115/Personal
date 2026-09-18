"""Type definitions and contracts for specialist delegation."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SpecialistDefinition(BaseModel):
    """Specification of an authorized specialist agent."""

    name: str
    description: str
    system_prompt_template: str
    allowed_tools: List[str]
    max_steps: int = 10
    timeout_seconds: float = 60.0
    preferred_model_capabilities: List[str] = Field(default_factory=lambda: ["code"])


class DelegationRequest(BaseModel):
    """Input payload requesting specialist delegation from orchestrator."""

    specialist_name: str
    task_description: str
    context: Dict[str, Any] = Field(default_factory=dict)
    parent_run_id: str
    parent_tool_call_id: Optional[str] = None
    session_id: str
    max_steps: Optional[int] = None
    timeout_seconds: Optional[float] = None


class DelegationResult(BaseModel):
    """Structured result returned by a specialist run to the root orchestrator."""

    specialist_name: str
    child_run_id: str
    status: str  # "completed", "failed", "cancelled"
    summary: str
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    steps_taken: int = 0
    error: Optional[str] = None
