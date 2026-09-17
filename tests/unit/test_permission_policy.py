"""Unit tests for the capability permission policy."""

import pytest
from app.approvals.capabilities import Capability
from app.approvals.policy import PermissionDecision, PermissionPolicy


def test_permission_read_automatic():
    policy = PermissionPolicy()
    decision = policy.evaluate([Capability.FILESYSTEM_READ.value], risk_level="LOW")
    assert decision == PermissionDecision.AUTOMATIC


def test_permission_write_requires_approval():
    policy = PermissionPolicy()
    decision = policy.evaluate([Capability.FILESYSTEM_WRITE.value], risk_level="HIGH")
    assert decision == PermissionDecision.REQUIRES_APPROVAL


def test_permission_shell_requires_approval():
    policy = PermissionPolicy()
    decision = policy.evaluate([Capability.SHELL_EXECUTE.value], risk_level="HIGH")
    assert decision == PermissionDecision.REQUIRES_APPROVAL


def test_permission_high_risk_requires_approval():
    policy = PermissionPolicy()
    # Even if capability is read, high risk level forces approval
    decision = policy.evaluate([Capability.FILESYSTEM_READ.value], risk_level="HIGH")
    assert decision == PermissionDecision.REQUIRES_APPROVAL


def test_permission_unknown_capability_requires_approval():
    policy = PermissionPolicy()
    decision = policy.evaluate(["unknown.danger.capability"], risk_level="LOW")
    assert decision == PermissionDecision.REQUIRES_APPROVAL
