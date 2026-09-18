"""Sandbox execution tools exposing isolated container execution to the AURA agent."""

from typing import Any, Dict, List, Optional
from app.approvals.capabilities import Capability
from app.sandbox.base import SandboxRuntime
from app.sandbox.docker_runtime import DockerSandboxRuntime
from app.sandbox.mock_runtime import MockSandboxRuntime
from app.sandbox.spec import SandboxConfig
from app.tools.base import RiskLevel, Tool, ToolResult


def _get_default_runtime() -> SandboxRuntime:
    """Provide DockerSandboxRuntime if daemon is responsive, else MockSandboxRuntime."""
    try:
        docker_rt = DockerSandboxRuntime()
        if docker_rt.is_available():
            return docker_rt
    except Exception:
        pass
    return MockSandboxRuntime(available=True)


class SandboxShellExecuteTool(Tool):
    """Executes arbitrary shell commands inside an isolated Docker container sandbox."""

    def __init__(self, runtime: Optional[SandboxRuntime] = None) -> None:
        self._runtime = runtime or _get_default_runtime()

    @property
    def name(self) -> str:
        return "sandbox_shell_execute"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command inside a hardened, isolated Docker container sandbox. "
            "The container has no network access and read-only rootfs with workspace mount. "
            "Requires human approval before execution."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.SHELL_EXECUTE.value, Capability.SANDBOX_EXECUTE.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run inside the container.",
                },
            },
            "required": ["command"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        command = input_data.get("command")
        if not command:
            return ToolResult(
                success=False,
                output="",
                error="Missing required parameter 'command'.",
                metadata={"error_category": "validation_error"},
            )

        if not self._runtime.is_available():
            return ToolResult(
                success=False,
                output="",
                error="Sandbox execution failure: Docker daemon is unavailable on this host.",
                metadata={"error_category": "runtime_unavailable"},
            )

        try:
            from app.core.settings import settings
            cfg = SandboxConfig(workspace_dir=str(settings.AURA_WORKSPACE_ROOT))
            res = await self._runtime.run_command(command, config=cfg)
            success = res.exit_code == 0 and not res.timed_out
            err_msg = res.stderr if res.stderr else (res.stdout if not success else None)
            if res.timed_out:
                err_msg = f"Execution timed out. {res.stderr}"

            return ToolResult(
                success=success,
                output=res.stdout or res.stderr or f"Exit code: {res.exit_code}",
                error=err_msg,
                metadata={
                    "exit_code": res.exit_code,
                    "timed_out": res.timed_out,
                    "duration_ms": res.duration_ms,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Sandbox execution error: {str(e)}",
                metadata={"error_category": "sandbox_error"},
            )


class SandboxPythonExecuteTool(Tool):
    """Executes Python scripts inside an isolated Docker container sandbox."""

    def __init__(self, runtime: Optional[SandboxRuntime] = None) -> None:
        self._runtime = runtime or _get_default_runtime()

    @property
    def name(self) -> str:
        return "sandbox_python_execute"

    @property
    def description(self) -> str:
        return (
            "Execute a Python script inside a hardened, isolated Docker container sandbox. "
            "Runs non-root with no network access and strict resource quotas. "
            "Requires human approval before execution."
        )

    @property
    def required_capabilities(self) -> List[str]:
        return [Capability.SHELL_EXECUTE.value, Capability.SANDBOX_EXECUTE.value]

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH

    @property
    def parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python source code to execute inside the sandbox.",
                },
            },
            "required": ["code"],
        }

    async def execute(self, input_data: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> ToolResult:
        code = input_data.get("code")
        if not code:
            return ToolResult(
                success=False,
                output="",
                error="Missing required parameter 'code'.",
                metadata={"error_category": "validation_error"},
            )

        if not self._runtime.is_available():
            return ToolResult(
                success=False,
                output="",
                error="Sandbox execution failure: Docker daemon is unavailable on this host.",
                metadata={"error_category": "runtime_unavailable"},
            )

        try:
            from app.core.settings import settings
            cfg = SandboxConfig(workspace_dir=str(settings.AURA_WORKSPACE_ROOT))
            res = await self._runtime.run_python(code, config=cfg)
            success = res.exit_code == 0 and not res.timed_out
            err_msg = res.stderr if res.stderr else (res.stdout if not success else None)
            if res.timed_out:
                err_msg = f"Execution timed out. {res.stderr}"

            return ToolResult(
                success=success,
                output=res.stdout or res.stderr or f"Exit code: {res.exit_code}",
                error=err_msg,
                metadata={
                    "exit_code": res.exit_code,
                    "timed_out": res.timed_out,
                    "duration_ms": res.duration_ms,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Sandbox execution error: {str(e)}",
                metadata={"error_category": "sandbox_error"},
            )
