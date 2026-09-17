"""Deterministic Mock Sandbox Runtime for test environments and offline verification."""

import re
from typing import Dict, Optional
from app.sandbox.base import SandboxRuntime
from app.sandbox.spec import ExecutionResult, SandboxConfig


class MockSandboxRuntime(SandboxRuntime):
    """
    Mock sandbox runtime that simulates container execution without requiring Docker daemon.
    Enables reproducible tests for approvals, errors, timeouts, and multi-turn tool interaction.
    """

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self._mock_responses: Dict[str, ExecutionResult] = {}
        self.invocations: list[tuple[str, str]] = []

    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def register_response(self, pattern: str, result: ExecutionResult) -> None:
        """Register canned ExecutionResult for a regex command or code pattern."""
        self._mock_responses[pattern] = result

    async def run_command(self, command: str, config: Optional[SandboxConfig] = None) -> ExecutionResult:
        self.invocations.append(("command", command))
        if not self._available:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Mock runtime is unavailable.",
                metadata={"mock": True},
            )

        for pat, res in self._mock_responses.items():
            if re.search(pat, command):
                return res

        # Default simulated success
        return ExecutionResult(
            exit_code=0,
            stdout=f"[MockSandbox stdout]: {command}\nDone.",
            stderr="",
            duration_ms=5.0,
            metadata={"mock": True, "command": command},
        )

    async def run_python(self, code: str, config: Optional[SandboxConfig] = None) -> ExecutionResult:
        self.invocations.append(("python", code))
        if not self._available:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Mock runtime is unavailable.",
                metadata={"mock": True},
            )

        for pat, res in self._mock_responses.items():
            if re.search(pat, code):
                return res

        # Default simulated python success
        return ExecutionResult(
            exit_code=0,
            stdout=f"[MockSandbox python output]: Executed successfully.\n{code.strip()}",
            stderr="",
            duration_ms=10.0,
            metadata={"mock": True},
        )
