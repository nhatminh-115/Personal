"""Explicit typed AgentState for LangGraph orchestration."""

from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
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
    tool_approvals: Dict[str, Dict[str, Any]]  # tool_call_id -> {"status": ..., "arguments": ..., "approval_id": ...}
    execution_status: str  # "running", "waiting_for_approval", "completed", "failed", "cancelled"
    errors: List[str]
    final_response: Optional[str]
    project_name: Optional[str]
    metadata: Optional[Dict[str, Any]]
    step_number: int
    max_steps: int
    total_tool_calls: int
    max_tool_calls: int
    consecutive_failures: int
    max_consecutive_failures: int
    deadline_seconds: Optional[float]
    start_time: Optional[float]
    termination_reason: Optional[str]
    delegation_context: Optional[Dict[str, Any]]


def create_initial_agent_state(
    run_id: str,
    session_id: str,
    user_message: str,
    project_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AgentState:
    """Canonical factory to produce an initialized AgentState for LangGraph runs."""
    import time
    meta = dict(metadata) if metadata else {}
    if project_name and "project_name" not in meta:
        meta["project_name"] = project_name

    max_steps = int(meta.get("max_steps", 10))
    max_tool_calls = int(meta.get("max_tool_calls", 25))
    max_consecutive_failures = int(meta.get("max_consecutive_failures", 3))
    timeout_budget = meta.get("timeout_seconds")
    start_ts = time.time()
    deadline = start_ts + float(timeout_budget) if timeout_budget else None

    return {
        "run_id": run_id,
        "session_id": session_id,
        "user_message": user_message,
        "messages": [],
        "retrieved_context": [],
        "current_plan": None,
        "tool_requests": [],
        "tool_results": [],
        "approval_id": None,
        "approval_state": "none",
        "tool_approvals": {},
        "execution_status": "running",
        "errors": [],
        "final_response": None,
        "project_name": project_name,
        "metadata": meta,
        "step_number": 1,
        "max_steps": max_steps,
        "total_tool_calls": 0,
        "max_tool_calls": max_tool_calls,
        "consecutive_failures": 0,
        "max_consecutive_failures": max_consecutive_failures,
        "deadline_seconds": deadline,
        "start_time": start_ts,
        "termination_reason": None,
        "delegation_context": meta.get("delegation_context"),
    }
