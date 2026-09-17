"""Unit tests for Docker Sandbox specifications and runtime abstractions."""

import pytest
from app.sandbox.docker_runtime import DockerSandboxRuntime
from app.sandbox.mock_runtime import MockSandboxRuntime
from app.sandbox.spec import ExecutionResult, SandboxConfig


def test_sandbox_config_hardened_defaults():
    """Verify default sandbox configuration enforces secure, unprivileged execution parameters."""
    cfg = SandboxConfig()
    assert cfg.user == "1000:1000"
    assert cfg.read_only_root is True
    assert cfg.network_disabled is True
    assert cfg.memory_limit == "512m"
    assert cfg.cpu_quota == 1.0
    assert cfg.pids_limit == 64
    assert cfg.workdir == "/workspace"
    assert cfg.container_workspace_mount == "/workspace"


@pytest.mark.asyncio
async def test_mock_sandbox_runtime_execution_and_custom_responses():
    """Verify MockSandboxRuntime handles commands, python execution, and custom simulated outputs."""
    runtime = MockSandboxRuntime()
    assert runtime.is_available() is True

    # 1. Default command execution
    res1 = await runtime.run_command("ls -la")
    assert res1.exit_code == 0
    assert "MockSandbox stdout" in res1.stdout
    assert len(runtime.invocations) == 1

    # 2. Default python execution
    res2 = await runtime.run_python("print(40 + 2)")
    assert res2.exit_code == 0
    assert "Executed successfully" in res2.stdout

    # 3. Custom registered failure response
    runtime.register_response(
        r"fail_command",
        ExecutionResult(exit_code=127, stdout="", stderr="command not found: fail_command"),
    )
    res_fail = await runtime.run_command("run fail_command now")
    assert res_fail.exit_code == 127
    assert "command not found" in res_fail.stderr

    # 4. Custom timeout response
    runtime.register_response(
        r"sleep_timeout",
        ExecutionResult(exit_code=-1, stdout="", stderr="Killed by SIGKILL", timed_out=True),
    )
    res_timeout = await runtime.run_command("sleep_timeout 100")
    assert res_timeout.timed_out is True
    assert res_timeout.exit_code == -1


def test_docker_runtime_is_available_graceful():
    """Verify DockerSandboxRuntime.is_available() gracefully returns boolean without uncaught crashes."""
    runtime = DockerSandboxRuntime()
    # Should not throw unhandled exception regardless of whether daemon is running
    is_avail = runtime.is_available()
    assert isinstance(is_avail, bool)
