"""Centralized permission policy engine."""

from enum import Enum
from typing import List, Set
from app.approvals.capabilities import Capability


class PermissionDecision(str, Enum):
    """Result of policy evaluation."""

    AUTOMATIC = "automatic"
    REQUIRES_APPROVAL = "requires_approval"
    DENIED = "denied"


class PermissionPolicy:
    """Evaluates requested tool capabilities and risk levels against security policies."""

    def __init__(self) -> None:
        # Capabilities that are pre-cleared for autonomous execution without human interruption
        self._automatic_capabilities: Set[str] = {
            Capability.FILESYSTEM_READ.value,
            Capability.MCP_READ.value,
        }

        # Capabilities that explicitly demand human verification before execution
        self._approval_required_capabilities: Set[str] = {
            Capability.FILESYSTEM_WRITE.value,
            Capability.SHELL_EXECUTE.value,
            Capability.NETWORK_ACCESS.value,
            Capability.EMAIL_SEND.value,
            Capability.GIT_WRITE.value,
            Capability.MCP_EXECUTE.value,
            Capability.SANDBOX_EXECUTE.value,
        }

    def evaluate(self, required_capabilities: List[str], risk_level: str = "LOW") -> PermissionDecision:
        """
        Determine if tool invocation is automatic, requires human approval, or denied.
        """
        # Risk level gate: HIGH or CRITICAL unconditionally triggers approval gate
        if risk_level.upper() in {"HIGH", "CRITICAL"}:
            return PermissionDecision.REQUIRES_APPROVAL

        # If any capability requires approval, the entire invocation requires approval
        for cap in required_capabilities:
            if cap in self._approval_required_capabilities:
                return PermissionDecision.REQUIRES_APPROVAL

        # Verify that all capabilities are explicitly known and automatic
        for cap in required_capabilities:
            if cap not in self._automatic_capabilities:
                # Default-deny / default-approval for unknown capabilities
                return PermissionDecision.REQUIRES_APPROVAL

        return PermissionDecision.AUTOMATIC


# Global permission policy instance
permission_policy = PermissionPolicy()
