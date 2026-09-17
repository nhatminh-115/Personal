"""Sandbox interfaces and contracts."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SandboxExecutionResult(BaseModel):
    """Result from an isolated sandbox execution."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SandboxExecutor(ABC):
    """Abstract contract for future containerized or jailed execution environments."""

    @abstractmethod
    async def execute_command(
        self,
        command: str,
        arguments: Optional[List[str]] = None,
        timeout_seconds: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> SandboxExecutionResult:
        """Run a command inside an isolated container sandbox."""
        pass
