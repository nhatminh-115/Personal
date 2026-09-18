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

    def __init__(self, available: bool = True, config: Optional[SandboxConfig] = None) -> None:
        self._available = available
        self._config = config or SandboxConfig()
        self._mock_responses: Dict[str, ExecutionResult] = {}
        self.invocations: list[tuple[str, str]] = []

    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def register_response(self, pattern: str, result: ExecutionResult) -> None:
        """Register canned ExecutionResult for a regex command or code pattern."""
        self._mock_responses[pattern] = result

    def _truncate_output(self, text: str, max_bytes: int) -> tuple[str, bool]:
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            truncated_text = encoded[:max_bytes].decode("utf-8", errors="replace")
            return truncated_text + "\n... [Output truncated: exceeded max_output_bytes limit]", True
        return text, False

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

        if "pytest" in command:
            import subprocess
            import sys
            from pathlib import Path
            from app.core.settings import settings
            ws = Path(settings.AURA_WORKSPACE_ROOT) if settings.AURA_WORKSPACE_ROOT else None
            if ws and ws.exists() and list(ws.glob("test_*.py")):
                try:
                    cmd_args = [sys.executable, "-m", "pytest", "-v"]
                    proc = subprocess.run(cmd_args, cwd=str(ws), capture_output=True, text=True, timeout=15.0)
                    cfg = config or self._config
                    stdout, truncated = self._truncate_output(proc.stdout, cfg.max_output_bytes)
                    stderr, _ = self._truncate_output(proc.stderr, cfg.max_output_bytes)
                    return ExecutionResult(
                        exit_code=proc.returncode,
                        stdout=stdout,
                        stderr=stderr,
                        duration_ms=25.0,
                        metadata={"mock": True, "real_pytest": True, "exit_code": proc.returncode},
                    )
                except Exception:
                    pass

        cfg = config or self._config
        stdout_raw = f"[MockSandbox stdout]: {command}\nDone."
        stdout, truncated = self._truncate_output(stdout_raw, cfg.max_output_bytes)
        meta = {"mock": True, "command": command}
        if truncated:
            meta["truncated"] = True

        return ExecutionResult(
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_ms=5.0,
            metadata=meta,
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

        cfg = config or self._config
        stdout_raw = f"[MockSandbox python output]: Executed successfully.\n{code.strip()}"
        stdout, truncated = self._truncate_output(stdout_raw, cfg.max_output_bytes)
        meta = {"mock": True}
        if truncated:
            meta["truncated"] = True

        return ExecutionResult(
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_ms=10.0,
            metadata=meta,
        )
