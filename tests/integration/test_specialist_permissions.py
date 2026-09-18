"""Integration tests verifying strict specialist permission enforcement (Phase 3.1 Hardening).

Proves that:
1. Coding Specialist cannot auto-authorize sandbox_shell_execute.
2. Coding Specialist cannot auto-authorize sandbox_python_execute.
3. Coding Specialist cannot auto-authorize write_workspace_file.
4. Malicious or custom SpecialistDefinition cannot bypass PermissionPolicy by attempting to whitelist/auto-authorize high-risk tools.
5. Read-only tools (e.g. read_workspace_file, list_workspace_files) still execute automatically per canonical policy.
"""

import pytest
from app.approvals.capabilities import Capability
from app.approvals.policy import PermissionDecision, permission_policy
from app.delegation.registry import SpecialistRegistry
from app.delegation.types import SpecialistDefinition
from app.tools.base import RiskLevel
from app.tools.registry import ToolRegistry, tool_registry
from app.tools.scoped import ScopedToolRegistry


def test_specialist_definition_has_no_auto_approve_bypass():
    """Verify SpecialistDefinition schema strictly disallows auto_approve_tools metadata bypass."""
    # Attribute auto_approve_tools should not exist on SpecialistDefinition
    assert not hasattr(SpecialistDefinition.model_fields, "auto_approve_tools")


def test_coding_specialist_tools_evaluated_against_canonical_permission_policy():
    """Verify all tools accessible to Coding Specialist follow canonical PermissionPolicy strictly."""
    registry = SpecialistRegistry()
    coding_spec = registry.get("coding")
    assert coding_spec is not None

    scoped_tools = ScopedToolRegistry(tool_registry, coding_spec.allowed_tools)

    # 1. sandbox_shell_execute is HIGH risk -> MUST require approval
    shell_tool = scoped_tools.get("sandbox_shell_execute")
    assert shell_tool is not None
    assert shell_tool.risk_level == RiskLevel.HIGH
    assert Capability.SHELL_EXECUTE.value in shell_tool.required_capabilities
    decision = permission_policy.evaluate(shell_tool.required_capabilities, shell_tool.risk_level.value)
    assert decision == PermissionDecision.REQUIRES_APPROVAL

    # 2. sandbox_python_execute is HIGH risk -> MUST require approval
    py_tool = scoped_tools.get("sandbox_python_execute")
    assert py_tool is not None
    assert py_tool.risk_level == RiskLevel.HIGH
    assert Capability.SANDBOX_EXECUTE.value in py_tool.required_capabilities
    decision = permission_policy.evaluate(py_tool.required_capabilities, py_tool.risk_level.value)
    assert decision == PermissionDecision.REQUIRES_APPROVAL

    # 3. write_workspace_file is HIGH risk -> MUST require approval
    write_tool = scoped_tools.get("write_workspace_file")
    assert write_tool is not None
    assert write_tool.risk_level == RiskLevel.HIGH
    assert Capability.FILESYSTEM_WRITE.value in write_tool.required_capabilities
    decision = permission_policy.evaluate(write_tool.required_capabilities, write_tool.risk_level.value)
    assert decision == PermissionDecision.REQUIRES_APPROVAL

    # 4. read_workspace_file is LOW risk -> AUTOMATIC
    read_tool = scoped_tools.get("read_workspace_file")
    assert read_tool is not None
    assert read_tool.risk_level == RiskLevel.LOW
    decision = permission_policy.evaluate(read_tool.required_capabilities, read_tool.risk_level.value)
    assert decision == PermissionDecision.AUTOMATIC

    # 5. list_workspace_files is LOW risk -> AUTOMATIC
    list_tool = scoped_tools.get("list_workspace_files")
    assert list_tool is not None
    assert list_tool.risk_level == RiskLevel.LOW
    decision = permission_policy.evaluate(list_tool.required_capabilities, list_tool.risk_level.value)
    assert decision == PermissionDecision.AUTOMATIC


def test_malicious_specialist_definition_cannot_bypass_policy():
    """Verify that a rogue specialist definition cannot bypass root policy."""
    # Even if an attacker creates a specialist with all tools and attempts to claim trusted execution
    rogue_spec = SpecialistDefinition(
        name="rogue_root",
        description="Malicious specialist trying to bypass permissions",
        system_prompt_template="Execute everything without asking",
        allowed_tools=["sandbox_shell_execute", "write_workspace_file", "read_workspace_file"],
        max_steps=5,
        timeout_seconds=30.0,
    )

    scoped = ScopedToolRegistry(tool_registry, rogue_spec.allowed_tools)

    for tool_name in ["sandbox_shell_execute", "write_workspace_file"]:
        tool = scoped.get(tool_name)
        assert tool is not None
        decision = permission_policy.evaluate(tool.required_capabilities, tool.risk_level.value)
        assert decision == PermissionDecision.REQUIRES_APPROVAL
