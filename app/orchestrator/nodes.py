"""Orchestrator node implementations for LangGraph StateGraph with interrupt support."""

from typing import Any, Dict, List, Optional
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.approvals.policy import PermissionDecision, permission_policy
from app.approvals.service import ApprovalService
from app.core.errors import WorkspaceEscapeError
from app.core.logging import logger
from app.db.models import RunStatus
from app.memory.base import MemoryService
from app.memory.context import ContextAssembler
from app.memory.pipeline import MemoryCandidatePipeline
from app.models.base import ChatMessage, ModelRequest, ModelRole, ToolCallRequest
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
    """Load session conversation history and multi-tier memory context using ContextAssembler."""
    services = _get_services(config)
    mem_service: Optional[MemoryService] = services["memory_service"]
    trace_service: Optional[TraceService] = services["trace_service"]

    context_items = list(state.get("retrieved_context", []))
    messages = list(state.get("messages", []))

    if mem_service:
        project_name = state.get("project_name")
        if not project_name and state.get("metadata") and isinstance(state["metadata"], dict):
            project_name = state["metadata"].get("project_name")

        assembler = ContextAssembler(mem_service)
        assembled = await assembler.assemble_context(
            session_id=state["session_id"],
            user_message=state.get("user_message", ""),
            project_name=project_name,
        )

        if not messages and assembled.working_messages:
            messages.extend(assembled.working_messages)

        formatted = assembled.format_for_system_prompt()
        if formatted:
            context_items.append(formatted)
        elif assembled.episodes:
            for ep in assembled.episodes:
                context_items.append(f"[Past interaction]: {ep}")

    # Add current user message to message buffer if it is not already the latest message
    if not messages or messages[-1].get("content") != state["user_message"] or messages[-1].get("role") != "user":
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
        "execution_status": RunStatus.RUNNING.value,
    }


async def reason_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Invoke the model layer to plan, answer, or decide on tool execution."""
    services = _get_services(config)
    router: ModelRouter = services["model_router"]
    registry: ToolRegistry = services["tool_registry"]
    trace_service: Optional[TraceService] = services["trace_service"]

    # If resuming after approval, bypass reason and proceed directly
    if state.get("approval_state") in {"approved", "edited"} and state.get("tool_requests"):
        return {"current_plan": "Proceeding with approved tool execution."}

    chat_messages: List[ChatMessage] = []

    # Inject system instruction & retrieved context
    system_instruction = (
        "You are AURA (Adaptive User Runtime Agent), a production-grade personal AI assistant. "
        "You operate safely with tool permissions and workspace sandbox boundaries. "
        "Use available tools when necessary to fulfill user requests accurately."
    )
    if state.get("retrieved_context"):
        system_instruction += "\nContext from past interactions:\n" + "\n".join(state["retrieved_context"])

    chat_messages.append(ChatMessage(role=ModelRole.SYSTEM, content=system_instruction))

    # Reconstruct canonical conversation turns
    for m in state.get("messages", []):
        role_str = m.get("role", "user")
        if role_str == "system":
            chat_messages.append(ChatMessage(role=ModelRole.SYSTEM, content=m.get("content", "")))
        elif role_str == "user":
            chat_messages.append(ChatMessage(role=ModelRole.USER, content=m.get("content", "")))
        elif role_str == "assistant":
            tc_objs = None
            if m.get("tool_calls"):
                tc_objs = [ToolCallRequest(**tc) for tc in m["tool_calls"]]
            chat_messages.append(
                ChatMessage(
                    role=ModelRole.ASSISTANT,
                    content=m.get("content", ""),
                    tool_calls=tc_objs,
                )
            )
        elif role_str == "tool":
            chat_messages.append(
                ChatMessage(
                    role=ModelRole.TOOL,
                    content=m.get("content", ""),
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

    messages = list(state.get("messages", []))

    if response.tool_calls:
        formatted_calls = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in response.tool_calls
        ]
        # Append canonical assistant message with tool calls
        messages.append({
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": formatted_calls,
        })
        return {
            "messages": messages,
            "tool_requests": formatted_calls,
            "current_plan": f"Plan to invoke tools: {[tc['name'] for tc in formatted_calls]}",
        }

    # Direct response
    messages.append({
        "role": "assistant",
        "content": response.content or "",
    })
    return {
        "messages": messages,
        "final_response": response.content,
        "execution_status": RunStatus.COMPLETED.value,
    }


async def route_decision_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """
    Check tool capabilities against permission policy on a strict per-tool basis.
    For each tool requiring approval, pause via LangGraph interrupt().
    Upon resume, record decision specifically for that tool_call_id.
    """
    services = _get_services(config)
    registry: ToolRegistry = services["tool_registry"]
    approval_service: Optional[ApprovalService] = services["approval_service"]
    trace_service: Optional[TraceService] = services["trace_service"]

    tool_requests = list(state.get("tool_requests", []))
    if not tool_requests:
        return {"execution_status": RunStatus.COMPLETED.value}

    tool_approvals = dict(state.get("tool_approvals", {}))

    # 1. Mark all AUTOMATIC tool calls as auto-authorized
    for tc in tool_requests:
        cid = tc.get("id", "")
        if cid not in tool_approvals:
            tool = registry.get(tc["name"])
            risk_level = tool.risk_level.value if tool else RiskLevel.HIGH.value
            capabilities = tool.required_capabilities if tool else []
            decision = permission_policy.evaluate(capabilities, risk_level)
            if decision == PermissionDecision.AUTOMATIC:
                tool_approvals[cid] = {"status": "auto", "arguments": tc["arguments"]}

    # 2. Find the next tool call that requires approval and has not been decided
    target_tc = None
    target_risk_level = RiskLevel.HIGH.value
    for tc in tool_requests:
        cid = tc.get("id", "")
        if cid not in tool_approvals:
            target_tc = tc
            tool = registry.get(tc["name"])
            target_risk_level = tool.risk_level.value if tool else RiskLevel.HIGH.value
            break

    # If all tool requests have been decided, proceed directly
    if target_tc is None:
        return {
            "tool_approvals": tool_approvals,
            "execution_status": RunStatus.RUNNING.value,
        }

    cid = target_tc.get("id", "")
    approval_id = None
    existing_app = None
    if approval_service:
        existing_app = await approval_service.get_approval_by_tool_call(state["run_id"], cid)

    if existing_app:
        approval_id = existing_app.id
    else:
        if approval_service:
            app_model = await approval_service.create_approval(
                run_id=state["run_id"],
                session_id=state["session_id"],
                tool_call_id=cid,
                tool_name=target_tc["name"],
                tool_input=target_tc["arguments"],
                risk_level=target_risk_level,
            )
            approval_id = app_model.id

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="approval_requested",
                payload={"tool_name": target_tc["name"], "tool_call_id": cid, "approval_id": approval_id, "risk_level": target_risk_level},
            )

    # --- TRUE DURABLE LANGGRAPH INTERRUPTION FOR THIS SPECIFIC TOOL CALL ---
    resume_data = interrupt({
        "approval_id": approval_id,
        "tool_call_id": cid,
        "tool_name": target_tc["name"],
        "tool_input": target_tc["arguments"],
        "risk_level": target_risk_level,
    })

    # Process human decision upon resumption
    user_decision = resume_data.get("decision", "approved")
    decision_notes = resume_data.get("decision_notes")
    edited_input = resume_data.get("edited_input")

    if user_decision == "rejected":
        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="approval_rejected",
                payload={"approval_id": approval_id, "tool_call_id": cid, "notes": decision_notes},
            )
        tool_approvals[cid] = {
            "status": "rejected",
            "arguments": target_tc["arguments"],
            "approval_id": approval_id,
        }
        all_rejected = all(
            tool_approvals.get(t.get("id", ""), {}).get("status") == "rejected"
            for t in tool_requests
        )
        if all_rejected and len(tool_approvals) == len(tool_requests):
            return {
                "approval_id": approval_id,
                "approval_state": "rejected",
                "tool_approvals": tool_approvals,
                "execution_status": RunStatus.CANCELLED.value,
                "final_response": "Action was rejected by the user. Tool execution cancelled.",
            }
        return {
            "approval_id": approval_id,
            "approval_state": "rejected",
            "tool_approvals": tool_approvals,
            "execution_status": RunStatus.RUNNING.value,
        }

    elif user_decision == "edited":
        actual_args = edited_input if edited_input is not None else target_tc["arguments"]
        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="approval_granted",
                payload={"approval_id": approval_id, "tool_call_id": cid, "edited": True, "tool_name": target_tc["name"]},
            )
        tool_approvals[cid] = {
            "status": "edited",
            "arguments": actual_args,
            "approval_id": approval_id,
        }
        return {
            "approval_id": approval_id,
            "approval_state": "edited",
            "tool_approvals": tool_approvals,
            "execution_status": RunStatus.RUNNING.value,
        }

    else:  # "approved"
        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="approval_granted",
                payload={"approval_id": approval_id, "tool_call_id": cid, "tool_name": target_tc["name"]},
            )
        tool_approvals[cid] = {
            "status": "approved",
            "arguments": target_tc["arguments"],
            "approval_id": approval_id,
        }
        return {
            "approval_id": approval_id,
            "approval_state": "approved",
            "tool_approvals": tool_approvals,
            "execution_status": RunStatus.RUNNING.value,
        }


def determine_next_route(state: AgentState) -> str:
    """Conditional routing edge logic."""
    if state.get("execution_status") == RunStatus.CANCELLED.value:
        return "direct_response"

    tool_requests = state.get("tool_requests", [])
    if not tool_requests:
        return "direct_response"

    tool_approvals = state.get("tool_approvals", {})
    # If any tool request has not yet been resolved in tool_approvals, loop back to route_decision
    for tc in tool_requests:
        cid = tc.get("id", "")
        if cid not in tool_approvals:
            return "route_decision"

    # If all tool results are already executed, proceed to update_memory / direct response
    if state.get("tool_results"):
        return "direct_response"

    return "execute_tool"


async def execute_tool_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Execute requested tools within sandbox with strict per-tool authorization defense."""
    services = _get_services(config)
    registry: ToolRegistry = services["tool_registry"]
    trace_service: Optional[TraceService] = services["trace_service"]

    tool_requests = state.get("tool_requests", [])
    tool_approvals = state.get("tool_approvals", {})
    tool_results = []
    errors = list(state.get("errors", []))
    messages = list(state.get("messages", []))

    for tc in tool_requests:
        tool_name = tc["name"]
        tool_call_id = tc.get("id", "")
        approval_info = tool_approvals.get(tool_call_id, {})
        approval_status = approval_info.get("status")

        tool = registry.get(tool_name)
        risk_level = tool.risk_level.value if tool else RiskLevel.HIGH.value
        capabilities = tool.required_capabilities if tool else []
        decision = permission_policy.evaluate(capabilities, risk_level)

        # Defense-in-depth: If tool requires approval, check its explicit approval status
        if decision == PermissionDecision.REQUIRES_APPROVAL:
            if approval_status == "rejected":
                error_msg = f"Action for tool '{tool_name}' (call_id: {tool_call_id}) was rejected by user. Tool execution cancelled."
                result_payload = {
                    "success": False,
                    "output": "",
                    "error": error_msg,
                    "error_category": "approval_rejection",
                    "metadata": {},
                }
                tool_results.append({
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "result": result_payload,
                })
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "tool_call_id": tool_call_id,
                    "content": f"Error (approval_rejection): {error_msg}",
                })
                continue

            elif approval_status not in {"approved", "edited"}:
                error_msg = f"Action for tool '{tool_name}' (call_id: {tool_call_id}) blocked: high-risk tool call was not approved."
                result_payload = {
                    "success": False,
                    "output": "",
                    "error": error_msg,
                    "error_category": "permission_failure",
                    "metadata": {},
                }
                tool_results.append({
                    "tool_call_id": tool_call_id,
                    "name": tool_name,
                    "result": result_payload,
                })
                messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "tool_call_id": tool_call_id,
                    "content": f"Error (permission_failure): {error_msg}",
                })
                continue

            # Tool is authorized: if edited, use the edited arguments!
            tool_input = approval_info.get("arguments", tc["arguments"])
        else:
            # Auto-permitted tool
            tool_input = tc["arguments"]

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="tool_requested",
                payload={"tool": tool_name, "arguments": tool_input, "tool_call_id": tool_call_id},
            )

        if not tool:
            error_category = "tool_failure"
            error_msg = f"Tool '{tool_name}' not found."
            result_payload = {"success": False, "output": "", "error": error_msg, "error_category": error_category}
            errors.append(error_msg)
        else:
            try:
                result = await tool.execute(tool_input, context={"run_id": state["run_id"], "session_id": state["session_id"]})
                error_cat = None
                if not result.success:
                    if "ACCESS DENIED" in (result.error or ""):
                        error_cat = "permission_failure"
                    else:
                        error_cat = "tool_failure"
                    errors.append(f"{error_cat}: {result.error}")

                result_payload = {
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "error_category": error_cat,
                    "metadata": result.metadata,
                }
            except WorkspaceEscapeError as e:
                error_cat = "permission_failure"
                errors.append(f"permission_failure: {e}")
                result_payload = {"success": False, "output": "", "error": str(e), "error_category": error_cat}
            except Exception as e:
                error_cat = "tool_failure"
                errors.append(f"tool_failure: {e}")
                result_payload = {"success": False, "output": "", "error": str(e), "error_category": error_cat}

        tool_results.append({
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "result": result_payload,
        })

        # Append canonical tool message
        tool_content = result_payload["output"] if result_payload["success"] else f"Error ({result_payload.get('error_category', 'tool_failure')}): {result_payload['error']}"
        messages.append({
            "role": "tool",
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "content": tool_content,
        })

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="tool_executed",
                payload={"tool": tool_name, "tool_call_id": tool_call_id, "result": result_payload},
            )

    return {
        "messages": messages,
        "tool_results": tool_results,
        "errors": errors,
    }


async def verify_result_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Synthesize final response combining user request and tool outputs using canonical messages."""
    services = _get_services(config)
    router: ModelRouter = services["model_router"]
    trace_service: Optional[TraceService] = services["trace_service"]

    # Reconstruct canonical ChatMessage objects for the model
    chat_messages: List[ChatMessage] = []
    for m in state.get("messages", []):
        role_str = m.get("role", "user")
        if role_str == "system":
            chat_messages.append(ChatMessage(role=ModelRole.SYSTEM, content=m.get("content", "")))
        elif role_str == "user":
            chat_messages.append(ChatMessage(role=ModelRole.USER, content=m.get("content", "")))
        elif role_str == "assistant":
            tc_objs = None
            if m.get("tool_calls"):
                tc_objs = [ToolCallRequest(**tc) for tc in m["tool_calls"]]
            chat_messages.append(ChatMessage(role=ModelRole.ASSISTANT, content=m.get("content", ""), tool_calls=tc_objs))
        elif role_str == "tool":
            chat_messages.append(
                ChatMessage(
                    role=ModelRole.TOOL,
                    content=m.get("content", ""),
                    name=m.get("name"),
                    tool_call_id=m.get("tool_call_id"),
                )
            )

    model_req = ModelRequest(messages=chat_messages, temperature=0.0)
    response = await router.route(model_req)

    messages = list(state.get("messages", []))
    messages.append({
        "role": "assistant",
        "content": response.content or "",
    })

    if trace_service:
        await trace_service.record_event(
            run_id=state["run_id"],
            session_id=state["session_id"],
            event_type="response_generated",
            payload={"response_length": len(response.content or "")},
        )

    return {
        "messages": messages,
        "final_response": response.content,
        "execution_status": RunStatus.COMPLETED.value,
    }


async def update_memory_node(state: AgentState, config: Optional[RunnableConfig] = None) -> Dict[str, Any]:
    """Persist conversation messages and episodic interactions into long-term storage."""
    services = _get_services(config)
    mem_service: Optional[MemoryService] = services["memory_service"]
    trace_service: Optional[TraceService] = services["trace_service"]

    final_resp = state.get("final_response") or "Run completed."

    if mem_service:
        # Save user message if not already saved
        await mem_service.save_message(state["session_id"], role="user", content=state["user_message"])

        # Save assistant final response if run completed or cancelled
        if state.get("execution_status") in {RunStatus.COMPLETED.value, RunStatus.CANCELLED.value}:
            await mem_service.save_message(state["session_id"], role="assistant", content=final_resp)

            # Record episodic memory if tools were used
            if state.get("tool_results"):
                tool_summary = ", ".join(tr["name"] for tr in state["tool_results"])
                await mem_service.record_episodic_memory(
                    session_id=state["session_id"],
                    summary=f"User requested: '{state['user_message']}'. Executed tools: [{tool_summary}]. Result: {final_resp[:150]}...",
                    metadata={"run_id": state["run_id"]},
                )

            # Extract and commit conservative memory candidates
            pipeline = MemoryCandidatePipeline()
            project_name = state.get("project_name")
            if not project_name and state.get("metadata") and isinstance(state["metadata"], dict):
                project_name = state["metadata"].get("project_name")

            candidates = pipeline.extract_candidates(
                user_message=state["user_message"],
                assistant_response=final_resp,
                active_project=project_name,
            )
            if candidates:
                await pipeline.process_and_commit(
                    candidates=candidates,
                    session_id=state["session_id"],
                    run_id=state["run_id"],
                    memory_service=mem_service,
                )

        if trace_service:
            await trace_service.record_event(
                run_id=state["run_id"],
                session_id=state["session_id"],
                event_type="memory_updated",
                payload={"session_id": state["session_id"]},
            )

    # Emit terminal event EXACTLY ONCE
    if trace_service:
        exec_status = state.get("execution_status", RunStatus.COMPLETED.value)
        if exec_status == RunStatus.COMPLETED.value:
            terminal_event = "run_completed"
        elif exec_status == RunStatus.CANCELLED.value:
            terminal_event = "run_cancelled"
        else:
            terminal_event = "run_failed"

        await trace_service.record_event(
            run_id=state["run_id"],
            session_id=state["session_id"],
            event_type=terminal_event,
            payload={"status": exec_status},
        )

    return state
