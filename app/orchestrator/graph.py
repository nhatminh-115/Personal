"""LangGraph StateGraph assembly and execution engine."""

from typing import Any, Dict
from langgraph.graph import END, START, StateGraph

from app.orchestrator.nodes import (
    approval_pause_node,
    determine_next_route,
    execute_tool_node,
    load_context_node,
    reason_node,
    route_decision_node,
    update_memory_node,
    verify_result_node,
)
from app.orchestrator.state import AgentState


def build_orchestrator_graph():
    """Build and compile the LangGraph StateGraph orchestrator."""
    workflow = StateGraph(AgentState)

    # 1. Register graph nodes
    workflow.add_node("load_context", load_context_node)
    workflow.add_node("reason", reason_node)
    workflow.add_node("route_decision", route_decision_node)
    workflow.add_node("execute_tool", execute_tool_node)
    workflow.add_node("verify_result", verify_result_node)
    workflow.add_node("approval_pause", approval_pause_node)
    workflow.add_node("update_memory", update_memory_node)

    # 2. Wire edges
    workflow.add_edge(START, "load_context")
    workflow.add_edge("load_context", "reason")
    workflow.add_edge("reason", "route_decision")

    # 3. Conditional routing from route_decision
    workflow.add_conditional_edges(
        "route_decision",
        determine_next_route,
        {
            "approval_pause": "approval_pause",
            "execute_tool": "execute_tool",
            "direct_response": "update_memory",
        },
    )

    workflow.add_edge("approval_pause", "update_memory")
    workflow.add_edge("execute_tool", "verify_result")
    workflow.add_edge("verify_result", "update_memory")
    workflow.add_edge("update_memory", END)

    return workflow.compile()


# Compiled singleton graph
orchestrator_graph = build_orchestrator_graph()


async def resume_execution(
    initial_state: AgentState,
    config: Dict[str, Any],
) -> AgentState:
    """
    Resume an agent run that was paused awaiting approval.
    Executes tool directly with approved state, verifies result, and updates memory.
    """
    # 1. Execute the approved tool
    tool_update = await execute_tool_node(initial_state, config)
    current_state = {**initial_state, **tool_update}

    # 2. Verify result and generate final response
    verify_update = await verify_result_node(current_state, config)
    current_state = {**current_state, **verify_update}

    # 3. Commit to memory and trace completion
    mem_update = await update_memory_node(current_state, config)
    return {**current_state, **mem_update}
