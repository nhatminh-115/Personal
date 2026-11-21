"""Keep model-generated delegation arguments out of trusted runtime scope."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.delegation.types import DelegationResult
from app.orchestrator.nodes import execute_tool_node
from app.tools.delegation import DelegateTaskTool


class _Registry:
    def __init__(self, tool):
        self.tool = tool

    def get(self, name):
        return self.tool if name == "delegate_task" else None


class _NoActiveRunDatabase:
    async def execute(self, _statement):
        return SimpleNamespace(one_or_none=lambda: None)


@pytest.mark.asyncio
async def test_model_context_cannot_override_delegated_project_or_routing_scope():
    trusted_routing_context = {
        "privacy_requirement": "local_only",
        "fallback_policy": "local_only",
        "require_cloud_confirmation": True,
    }
    runtime = SimpleNamespace(
        delegate=AsyncMock(
            return_value=DelegationResult(
                specialist_name="research",
                child_run_id="child-run",
                status="completed",
                summary="done",
                steps_taken=1,
            )
        )
    )
    tool = DelegateTaskTool(runtime=runtime)
    database = _NoActiveRunDatabase()
    model_context = {
        "project_name": "OtherProject",
        "routing_context_dict": {
            "privacy_requirement": "public",
            "fallback_policy": "cloud_allowed",
            "require_cloud_confirmation": False,
        },
        "profile_id": "attacker-profile",
        "winning_scope": "message",
        "is_lock_all": True,
        "model_override": "openai:unapproved-model",
        "reasoning_override": "max",
        "is_specialist": True,
    }
    state = {
        "run_id": "parent-run",
        "session_id": "session",
        "project_name": "TrustedProject",
        "metadata": {
            "routing_context_dict": trusted_routing_context,
            "profile_id": "trusted-profile",
            "winning_scope": "project",
            "is_lock_all": False,
            "reasoning_override": "low",
        },
        "tool_requests": [
            {
                "id": "call-1",
                "name": "delegate_task",
                "arguments": {
                    "specialist_name": "research",
                    "task_description": "Inspect the requested sources.",
                    # Older or nonconforming providers may still return this field.
                    "context": model_context,
                },
            }
        ],
        "tool_approvals": {},
        "messages": [],
        "tool_results": [],
        "errors": [],
        "total_tool_calls": 0,
    }

    await execute_tool_node(
        state,
        {
            "configurable": {
                "db": database,
                "tool_registry": _Registry(tool),
            }
        },
    )

    request = runtime.delegate.await_args.args[0]
    assert request.context["project_name"] == "TrustedProject"
    assert request.context["routing_context_dict"] == trusted_routing_context
    assert request.context["profile_id"] == "trusted-profile"
    assert request.context["winning_scope"] == "project"
    assert request.context["is_lock_all"] is False
    assert request.context["reasoning_override"] == "low"
    assert "model_override" not in request.context
    assert request.context.get("is_specialist") is not True
    assert "context" not in tool.parameters_schema["properties"]
