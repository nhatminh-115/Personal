"""Explicit typed AgentState for LangGraph orchestration."""

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict):
    """
    Explicit, typed state container passed through the LangGraph runtime.
    """

    run_id: str
    session_id: str
    user_message: str
    messages: List[Dict[str, Any]]
    retrieved_context: List[str]
    current_plan: Optional[str]
    tool_requests: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    approval_id: Optional[str]
    approval_state: str  # "none", "pending", "approved", "rejected", "edited"
    execution_status: str  # "running", "waiting_for_approval", "completed", "failed"
    errors: List[str]
    final_response: Optional[str]
