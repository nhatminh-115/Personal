"""Orchestrator node implementations for LangGraph StateGraph."""

import json
from typing import Any, Dict, Optional
from langchain_core.runnables import RunnableConfig

from app.approvals.policy import PermissionDecision, permission_policy
from app.approvals.service import ApprovalService
from app.core.logging import logger
from app.memory.base import MemoryService
from app.models.base import ChatMessage, ModelRequest, ModelRole
from app.models.router import ModelRouter, model_router
from app.observability.tracer import TraceService
from app.orchestrator.state import AgentState
from app.tools.base import RiskLevel
from app.tools.registry import ToolRegistry, tool_registry


def _get_services(config: Optional[RunnableConfig]) -> Dict[str, Any]:
    """Extract injected runtime services from LangGraph config."""
    configurable = config.get("configurable", {}) if config else {}
    return {
        "memory_service": configurable.get("memory_service"),
        "approval_service": configurable.get("approval_service"),
        "trace_service": configurable.get("trace_service"),
        "tool_registry": configurable.get("tool_registry", tool_registry),
        "model_router": configurable.get("model_router", model_router),
    }


async def load_context_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Load session conversation history and episodic memory context."""
    services = _get_services(config)
    mem_service: Optional[MemoryService] = services["memory_service"]
    trace_service: Optional[TraceService] = services["trace_service"]

    context_items = []
    messages = list(state.get("messages", []))

    if mem_service:
        # Load recent session messages from database if state messages are empty
        if not messages:
            db_msgs = await mem_service.get_session_messages(state["session_id"], limit=20)
            for m in db_msgs:
                messages.append({"role": m.role, "content": m.content})

        # Load recent episodic memories for contextual grounding
        episodes = await mem_service.get_recent_episodes(state["session_id"], limit=3)
        for ep in episodes:
            context_items.append(f"[Past interaction]: {ep.content}")

    # Add current user message to message buffer if not present
    if not any(m.get("content") == state["user_message"] for m in messages):
        messages.append({"role": "user", "content": state["user_message"]})

    if trace_service:
        await trace_service.record_event(
            run_id=state["run_id"],
            session_id=state["session_id"],
            event_type="context_loaded",
            payload={"context_count": len(context_items), "history_length": len(messages)},
        )

    return {
        "messages": messages,
        "retrieved_context": context_items,
        "execution_status": "running",
    }


async def reason_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Invoke the model layer to plan, answer, or decide on tool execution."""
    services = _get_services(config)
    router: ModelRouter = services["model_router"]
    registry: ToolRegistry = services["tool_registry"]
    trace_service: Optional[TraceService] = services["trace_service"]

    # If we are resuming after approval, bypass initial reason and go straight to execution
    if state.get("approval_state") == "approved" and state.get("tool_requests"):
        return {"current_plan": "Proceeding with approved tool execution."}

    chat_messages: list[ChatMessage] = []

    # Inject system instruction & retrieved context
    system_instruction = (
        "You are AURA (Adaptive User Runtime Agent), a production-grade personal AI assistant. "
        "You operate safely with tool permissions and workspace sandbox boundaries. "
        "Use available tools when necessary to fulfill user requests accurately."
    )
    if state.get("retrieved_context"):
        system_instruction += "\nContext from past interactions:\n" + "\n".join(state["retrieved_context"])

    chat_messages.append(ChatMessage(role=ModelRole.SYSTEM, content=system_instruction))

    # Add conversation turns
    for m in state.get("messages", []):
        role_map = {
            "user": ModelRole.USER,
            "assistant": ModelRole.ASSISTANT,
            "system": ModelRole.SYSTEM,
            "tool": ModelRole.TOOL,
        }
        chat_messages.append(
            ChatMessage(
                role=role_map.get(m["role"], ModelRole.USER),
                content=m["content"],
                name=m.get("name"),
                tool_call_id=m.get("tool_call_id"),
            )
        )

    tool_defs = registry.get_tool_definitions()

    model_req = ModelRequest(
        messages=chat_messages,
        tools=tool_defs,
        temperature=0.0,
    )

    if trace_service:
        await trace_service.record_event(
            run_id=state["run_id"],
            session_id=state["session_id"],
            event_type="model_called",
            payload={"messages_count": len(chat_messages), "tools_count": len(tool_defs)},
        )

    response = await router.route(model_req)

    if response.tool_calls:
        formatted_calls = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in response.tool_calls
        ]
        return {
            "tool_requests": formatted_calls,
            "current_plan": f"Plan to invoke tools: {[tc['name'] for tc in formatted_calls]}",
        }

    return {
        "final_response": response.content,
        "execution_status": "completed",
    }


async def route_decision_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Check tool capabilities against permission policy and trigger approval if needed."""
    services = _get_services(config)
    registry: ToolRegistry = services["tool_registry"]
    approval_service: Optional[ApprovalService] = services["approval_service"]
    trace_service: Optional[TraceService] = services["trace_service"]

    tool_requests = state.get("tool_requests", [])
    if not tool_requests:
        return {"execution_status": "completed"}

    # If already approved by user in a resumed turn, proceed directly
    if state.get("approval_state") == "approved":
        return {"execution_status": "running"}

    for tc in tool_requests:
        tool = registry.get(tc["name"])
        risk_level = tool.risk_level.value if tool else RiskLevel.HIGH.value
        capabilities = tool.required_capabilities if tool else []

        decision = permission_policy.evaluate(capabilities, risk_level)

        if decision == PermissionDecision.REQUIRES_APPROVAL:
            # Action requires human-in-the-loop approval
            approval_id = None
            if approval_service:
                app_model = await approval_service.create_approval(
                    run_id=state["run_id"],
                    session_id=state["session_id"],
                    tool_name=tc["name"],
                    tool_input=tc["arguments"],
                    risk_level=risk_level,
                )
                approval_id = app_model.id

            if trace_service:
                await trace_service.record_event(
                    run_id=state["run_id"],
                    session_id=state["session_id"],
                    event_type="approval_requested",
                    payload={"tool_name": tc["name"], "approval_id": approval_id, "risk_level": risk_level},
                )

            return {
                "approval_id": approval_id,
                "approval_state": "pending",
                "execution_status": "waiting_for_approval",
                "final_response": f"Action requires human approval: Tool '{tc['name']}' has risk level '{risk_level}'. Approval ID: {approval_id}",
            }

    return {"execution_status": "running"}


def determine_next_route(state: AgentState) -> str:
    """Conditional routing edge logic."""
    if state.get("execution_status") == "waiting_for_approval":
        return "approval_pause"
    if state.get("tool_requests") and not state.get("tool_results"):
        return "execute_tool"
    return "direct_response"


async def execute_tool_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Execute requested tools within sandbox and collect results."""
    services = _get_services(config)
    registry: ToolRegistry = services["tool_registry"]
    trace_service: Optional[TraceService] = services["trace_service"]

    tool_requests = state.get("tool_requests", [])
    tool_results = []

    for tc in tool_requests:
        tool_name = tc["name"]
        tool_input = tc["arguments"]

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="tool_requested",
                payload={"tool": tool_name, "arguments": tool_input},
            )

        tool = registry.get(tool_name)
        if not tool:
            result_payload = {"success": False, "output": "", "error": f"Tool '{tool_name}' not found."}
        else:
            result = await tool.execute(tool_input, context={"run_id": state["run_id"], "session_id": state["session_id"]})
            result_payload = {
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "metadata": result.metadata,
            }

        tool_results.append({
            "tool_call_id": tc.get("id", ""),
            "name": tool_name,
            "result": result_payload,
        })

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="tool_executed",
                payload={"tool": tool_name, "result": result_payload},
            )

    return {
        "tool_results": tool_results,
    }


async def verify_result_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Synthesize final response combining user request and tool outputs."""
    services = _get_services(config)
    router: ModelRouter = services["model_router"]
    trace_service: Optional[TraceService] = services["trace_service"]

    tool_results = state.get("tool_results", [])
    messages: list[ChatMessage] = []

    # Reconstruct messages with tool response
    for m in state.get("messages", []):
        messages.append(ChatMessage(role=ModelRole.USER if m["role"] == "user" else ModelRole.ASSISTANT, content=m["content"]))

    # Append tool output as tool message
    for tr in tool_results:
        content = tr["result"]["output"] if tr["result"]["success"] else f"Error: {tr['result']['error']}"
        messages.append(
            ChatMessage(
                role=ModelRole.TOOL,
                content=content,
                name=tr["name"],
                tool_call_id=tr["tool_call_id"],
            )
        )

    model_req = ModelRequest(messages=messages, temperature=0.0)
    response = await router.route(model_req)

    if trace_service:
        await trace_service.record_event(
            run_id=state["run_id"],
            session_id=state["session_id"],
            event_type="response_generated",
            payload={"response_length": len(response.content or "")},
        )

    return {
        "final_response": response.content,
        "execution_status": "completed",
    }


async def approval_pause_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Execution paused state awaiting user approval decision."""
    return {
        "execution_status": "waiting_for_approval",
    }


async def update_memory_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Persist conversation messages and episodic interactions into long-term storage."""
    services = _get_services(config)
    mem_service: Optional[MemoryService] = services["memory_service"]
    trace_service: Optional[TraceService] = services["trace_service"]

    final_resp = state.get("final_response") or "Run completed."

    if mem_service:
        # Save user message if not previously saved in working memory
        await mem_service.save_message(state["session_id"], role="user", content=state["user_message"])

        # Save assistant final response if run completed
        if state.get("execution_status") == "completed":
            await mem_service.save_message(state["session_id"], role="assistant", content=final_resp)

            # Record episodic memory if tools were used
            if state.get("tool_results"):
                tool_summary = ", ".join(tr["name"] for tr in state["tool_results"])
                await mem_service.record_episodic_memory(
                    session_id=state["session_id"],
                    summary=f"User requested: '{state['user_message']}'. Executed tools: [{tool_summary}]. Result: {final_resp[:150]}...",
                    metadata={"run_id": state["run_id"]},
                )

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="memory_updated",
                payload={"session_id": state["session_id"]},
            )

    # Final trace event
    if trace_service:
        terminal_event = "run_completed" if state.get("execution_status") == "completed" else (
            "approval_requested" if state.get("execution_status") == "waiting_for_approval" else "run_failed"
        )
        await trace_service.record_event(
            run_id=state["run_id"],
            session_id=state["session_id"],
            event_type=terminal_event,
            payload={"status": state.get("execution_status")},
        )

    return state
