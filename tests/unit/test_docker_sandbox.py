"""Unit tests for Docker Sandbox specifications and runtime abstractions."""

import os
import stat
from unittest.mock import MagicMock

import pytest
from app.core.errors import AURAError
from app.sandbox.docker_runtime import DockerSandboxRuntime
from app.sandbox.mock_runtime import MockSandboxRuntime
from app.sandbox.spec import ExecutionResult, SandboxConfig
from app.sandbox.tools import _get_default_runtime


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


@pytest.mark.asyncio
async def test_mock_sandbox_never_executes_pytest_on_the_host(tmp_path, monkeypatch):
    import subprocess
    from app.core.settings import settings

    (tmp_path / "test_untrusted.py").write_text("raise RuntimeError('must not execute')", encoding="utf-8")
    monkeypatch.setattr(settings, "AURA_WORKSPACE_ROOT", str(tmp_path))
    runtime = MockSandboxRuntime()

    def reject_host_execution(*args, **kwargs):
        raise AssertionError("mock sandbox attempted host process execution")

    monkeypatch.setattr(subprocess, "run", reject_host_execution)
    result = await runtime.run_command("pytest -q")

    assert result.exit_code == 0
    assert result.metadata.get("mock") is True
    assert "MockSandbox stdout" in result.stdout
    assert "real_pytest" not in result.metadata


def test_default_sandbox_runtime_fails_closed_when_docker_is_unavailable(monkeypatch):
    monkeypatch.setattr(DockerSandboxRuntime, "is_available", lambda self: False)

    runtime = _get_default_runtime()

    assert isinstance(runtime, MockSandboxRuntime)
    assert runtime.is_available() is False


def test_docker_runtime_is_available_graceful():
    """Verify DockerSandboxRuntime.is_available() gracefully returns boolean without uncaught crashes."""
    runtime = DockerSandboxRuntime()
    # Should not throw unhandled exception regardless of whether daemon is running
    is_avail = runtime.is_available()
    assert isinstance(is_avail, bool)


def test_docker_runtime_preserves_private_workspace_permissions(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX workspace mode bits are not available on Windows")

    workspace = tmp_path / "private-workspace"
    workspace.mkdir(mode=0o700)
    workspace.chmod(0o700)
    before_mode = stat.S_IMODE(workspace.stat().st_mode)

    container = MagicMock()
    container.id = "fake-container-id"
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    client = MagicMock()
    client.containers.create.return_value = container
    runtime = DockerSandboxRuntime()
    monkeypatch.setattr(runtime, "_get_client", lambda: client)

    result = runtime._execute_sync(["true"], SandboxConfig(workspace_dir=str(workspace)))

    assert result.exit_code == 0
    assert stat.S_IMODE(workspace.stat().st_mode) == before_mode == 0o700


def test_docker_runtime_creates_workspace_with_private_permissions(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX workspace mode bits are not available on Windows")

    workspace = tmp_path / "new-workspace"
    container = MagicMock()
    container.id = "fake-container-id"
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    client = MagicMock()
    client.containers.create.return_value = container
    runtime = DockerSandboxRuntime()
    monkeypatch.setattr(runtime, "_get_client", lambda: client)

    result = runtime._execute_sync(["true"], SandboxConfig(workspace_dir=str(workspace)))

    assert result.exit_code == 0
    assert stat.S_IMODE(workspace.stat().st_mode) == 0o700


def test_docker_runtime_never_pulls_missing_sandbox_image(tmp_path, monkeypatch):
    from app.sandbox import docker_runtime as docker_runtime_module

    class FakeImageNotFound(Exception):
        pass

    monkeypatch.setattr(docker_runtime_module, "ImageNotFound", FakeImageNotFound)
    client = MagicMock()
    client.images.get.side_effect = FakeImageNotFound("missing image")
    runtime = DockerSandboxRuntime()
    monkeypatch.setattr(runtime, "_get_client", lambda: client)

    with pytest.raises(AURAError, match="will not pull sandbox images automatically"):
        runtime._execute_sync(["true"], SandboxConfig(workspace_dir=str(tmp_path)))

    client.images.pull.assert_not_called()
    client.containers.create.assert_not_called()
