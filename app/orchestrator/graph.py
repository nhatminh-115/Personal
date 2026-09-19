"""LangGraph StateGraph assembly and durable checkpointer management."""

from pathlib import Path
from typing import Optional
import aiosqlite
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.logging import logger
from app.core.settings import settings
from app.orchestrator.nodes import (
    determine_next_route,
    determine_post_observe_route,
    execute_tool_node,
    load_context_node,
    observe_node,
    reason_node,
    route_decision_node,
    update_memory_node,
)
from app.orchestrator.state import AgentState

# Global checkpointer and compiled graph cache
_global_checkpointer: Optional[BaseCheckpointSaver] = None
_checkpointer_connection: Optional[aiosqlite.Connection] = None
_checkpointer_path: Optional[str] = None
_compiled_graph: Optional[CompiledStateGraph] = None


def build_orchestrator_graph() -> StateGraph:
    """Build the LangGraph StateGraph topology."""
    workflow = StateGraph(AgentState)

    # 1. Register graph nodes
    workflow.add_node("load_context", load_context_node)
    workflow.add_node("reason", reason_node)
    workflow.add_node("route_decision", route_decision_node)
    workflow.add_node("execute_tool", execute_tool_node)
    workflow.add_node("observe", observe_node)
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
            "route_decision": "route_decision",
            "execute_tool": "execute_tool",
            "direct_response": "update_memory",
        },
    )

    # 4. Iterative loop: execute_tool -> observe -> conditional(reason | update_memory)
    workflow.add_edge("execute_tool", "observe")
    workflow.add_conditional_edges(
        "observe",
        determine_post_observe_route,
        {
            "reason": "reason",
            "update_memory": "update_memory",
        },
    )
    workflow.add_edge("update_memory", END)

    return workflow


async def init_checkpointer(db_path: Optional[Path] = None) -> BaseCheckpointSaver:
    """Initialize persistent SQLite checkpointer for durable execution state."""
    global _global_checkpointer, _checkpointer_connection, _checkpointer_path, _compiled_graph
    target_path = str(db_path or settings.CHECKPOINT_DB_PATH)
    
    if _checkpointer_connection is not None:
        await _checkpointer_connection.close()

    _checkpointer_connection = await aiosqlite.connect(target_path)
    _global_checkpointer = AsyncSqliteSaver(_checkpointer_connection)
    await _global_checkpointer.setup()
    _checkpointer_path = target_path
    
    # Invalidate cached graph so it recompiles with new checkpointer
    _compiled_graph = None
    logger.info(f"Initialized LangGraph AsyncSqliteSaver checkpoint storage at '{target_path}'")
    return _global_checkpointer


def get_active_checkpointer_path() -> Optional[str]:
    """Return the database file path of the currently active checkpointer connection."""
    return _checkpointer_path


def set_global_checkpointer(checkpointer: BaseCheckpointSaver) -> None:
    """Explicitly set a checkpointer (useful for in-memory testing)."""
    global _global_checkpointer, _compiled_graph, _checkpointer_path
    _global_checkpointer = checkpointer
    _compiled_graph = None
    _checkpointer_path = None


async def close_checkpointer() -> None:
    """Gracefully close checkpointer connection upon application shutdown."""
    global _checkpointer_connection, _global_checkpointer, _checkpointer_path, _compiled_graph
    if _checkpointer_connection:
        await _checkpointer_connection.close()
        _checkpointer_connection = None
    _global_checkpointer = None
    _compiled_graph = None
    _checkpointer_path = None


async def get_compiled_graph(checkpointer: Optional[BaseCheckpointSaver] = None) -> CompiledStateGraph:
    """Retrieve or build the compiled LangGraph with durable checkpointer."""
    global _compiled_graph
    if checkpointer is not None:
        workflow = build_orchestrator_graph()
        return workflow.compile(checkpointer=checkpointer)

    if _compiled_graph is None:
        cp = _global_checkpointer
        if cp is None:
            cp = await init_checkpointer()
        workflow = build_orchestrator_graph()
        _compiled_graph = workflow.compile(checkpointer=cp)

    return _compiled_graph
