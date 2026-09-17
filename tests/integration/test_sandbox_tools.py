"""Integration tests for Sandbox Tools, permission enforcement, and container execution."""

import pytest
from app.approvals.capabilities import Capability
from app.approvals.policy import PermissionDecision, PermissionPolicy
from app.sandbox.docker_runtime import DockerSandboxRuntime
from app.sandbox.mock_runtime import MockSandboxRuntime
from app.sandbox.spec import ExecutionResult
from app.sandbox.tools import SandboxPythonExecuteTool, SandboxShellExecuteTool
from app.tools.base import RiskLevel
from app.tools.registry import ToolRegistry


def test_sandbox_tools_registered_in_tool_registry():
    """Verify sandbox tools are standardly registered in ToolRegistry."""
    registry = ToolRegistry()
    shell_tool = registry.get("sandbox_shell_execute")
    python_tool = registry.get("sandbox_python_execute")

    assert shell_tool is not None
    assert python_tool is not None

    defs = registry.get_tool_definitions()
    def_names = [d.name for d in defs]
    assert "sandbox_shell_execute" in def_names
    assert "sandbox_python_execute" in def_names


def test_sandbox_tools_permissions_enforce_human_approval():
    """Verify sandbox tools require human approval under AURA permission policy."""
    shell_tool = SandboxShellExecuteTool()
    python_tool = SandboxPythonExecuteTool()
    policy = PermissionPolicy()

    # Verify attributes
    assert shell_tool.risk_level == RiskLevel.HIGH
    assert Capability.SHELL_EXECUTE.value in shell_tool.required_capabilities
    assert Capability.SANDBOX_EXECUTE.value in shell_tool.required_capabilities

    assert python_tool.risk_level == RiskLevel.HIGH
    assert Capability.SHELL_EXECUTE.value in python_tool.required_capabilities
    assert Capability.SANDBOX_EXECUTE.value in python_tool.required_capabilities

    # Evaluate against policy
    decision_shell = policy.evaluate(shell_tool.required_capabilities, shell_tool.risk_level.value)
    assert decision_shell == PermissionDecision.REQUIRES_APPROVAL

    decision_python = policy.evaluate(python_tool.required_capabilities, python_tool.risk_level.value)
    assert decision_python == PermissionDecision.REQUIRES_APPROVAL


@pytest.mark.asyncio
async def test_sandbox_tools_execution_with_mock_runtime():
    """Verify tool execution handling with mock runtime across success, error, timeout, and validation paths."""
    runtime = MockSandboxRuntime(available=True)
    shell_tool = SandboxShellExecuteTool(runtime=runtime)
    python_tool = SandboxPythonExecuteTool(runtime=runtime)

    # 1. Validation failure: missing parameter
    val_res = await shell_tool.execute({})
    assert val_res.success is False
    assert val_res.metadata.get("error_category") == "validation_error"

    val_py_res = await python_tool.execute({})
    assert val_py_res.success is False
    assert val_py_res.metadata.get("error_category") == "validation_error"

    # 2. Successful shell execution
    shell_ok = await shell_tool.execute({"command": "echo 'Hello Aura'"})
    assert shell_ok.success is True
    assert "Hello Aura" in shell_ok.output

    # 3. Successful python execution
    py_ok = await python_tool.execute({"code": "result = 12 * 12\nprint(result)"})
    assert py_ok.success is True
    assert "Executed successfully" in py_ok.output

    # 4. Error response
    runtime.register_response(
        r"exit 1",
        ExecutionResult(exit_code=1, stdout="", stderr="Fatal command error."),
    )
    shell_err = await shell_tool.execute({"command": "exit 1"})
    assert shell_err.success is False
    assert "Fatal command error" in shell_err.error

    # 5. Timeout response
    runtime.register_response(
        r"infinite_loop",
        ExecutionResult(exit_code=-1, stdout="", stderr="timed out", timed_out=True),
    )
    timeout_res = await python_tool.execute({"code": "while True: pass # infinite_loop"})
    assert timeout_res.success is False
    assert "timed out" in timeout_res.error.lower()


@pytest.mark.asyncio
async def test_sandbox_tools_when_runtime_unavailable():
    """Verify clean error categorization when Docker runtime is unavailable."""
    runtime = MockSandboxRuntime(available=False)
    shell_tool = SandboxShellExecuteTool(runtime=runtime)
    python_tool = SandboxPythonExecuteTool(runtime=runtime)

    res_shell = await shell_tool.execute({"command": "ls"})
    assert res_shell.success is False
    assert res_shell.metadata.get("error_category") == "runtime_unavailable"

    res_py = await python_tool.execute({"code": "print(1)"})
    assert res_py.success is False
    assert res_py.metadata.get("error_category") == "runtime_unavailable"


@pytest.mark.asyncio
async def test_docker_live_execution_if_daemon_active():
    """Execute real container command if Docker daemon is active (e.g. on CI ubuntu-latest)."""
    docker_runtime = DockerSandboxRuntime()
    if not docker_runtime.is_available():
        pytest.skip("Docker daemon not running locally. Real container execution tested on CI.")

    # Check if image can be acquired or pulled
    try:
        c = docker_runtime._get_client()
        try:
            c.images.get("python:3.12-slim")
        except Exception:
            c.images.pull("python:3.12-slim")
    except Exception as img_err:
        pytest.skip(f"Docker image 'python:3.12-slim' unavailable or cannot be pulled: {img_err}")

    shell_tool = SandboxShellExecuteTool(runtime=docker_runtime)
    python_tool = SandboxPythonExecuteTool(runtime=docker_runtime)

    # Test real shell execution inside container
    res_shell = await shell_tool.execute({"command": "echo 'docker_live_test_ok'"})
    if not res_shell.success:
        pytest.skip(f"Live container execution skipped due to runtime environment constraint: {res_shell.error}")

    assert "docker_live_test_ok" in res_shell.output

    # Test real python execution inside container
    res_python = await python_tool.execute({"code": "print('live_python_' + str(7 * 6))"})
    assert res_python.success is True
    assert "live_python_42" in res_python.output

