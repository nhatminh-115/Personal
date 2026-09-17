"""Abstract base class interface for execution sandbox runtimes."""

from abc import ABC, abstractmethod
from typing import Optional
from app.sandbox.spec import ExecutionResult, SandboxConfig


class SandboxRuntime(ABC):
    """Abstract interface for isolated execution environments."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether the underlying runtime engine (e.g. Docker daemon) is accessible."""
        pass

    @abstractmethod
    async def run_command(self, command: str, config: Optional[SandboxConfig] = None) -> ExecutionResult:
        """Execute a raw shell command inside the sandbox."""
        pass

    @abstractmethod
    async def run_python(self, code: str, config: Optional[SandboxConfig] = None) -> ExecutionResult:
        """Execute Python source code inside the sandbox."""
        pass
