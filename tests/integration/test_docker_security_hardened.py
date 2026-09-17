"""Real Docker sandbox security hardening tests."""

import os
import tempfile
import pytest

from app.sandbox.docker_runtime import DockerSandboxRuntime
from app.sandbox.spec import SandboxConfig


@pytest.fixture
def docker_runtime():
    runtime = DockerSandboxRuntime()
    if not runtime.is_available():
        pytest.skip("Docker daemon not available on host.")
    return runtime


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.mark.asyncio
async def test_docker_security_non_root_user(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify code executes as non-root user (UID 1000)."""
    cfg = SandboxConfig(workspace_dir=temp_workspace, timeout_seconds=10.0)
    res = await docker_runtime.run_command("id -u", config=cfg)
    assert res.exit_code == 0
    assert res.stdout.strip() == "1000"


@pytest.mark.asyncio
async def test_docker_security_read_only_rootfs(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify that root filesystem is mounted read-only and prevents arbitrary writes."""
    cfg = SandboxConfig(workspace_dir=temp_workspace, timeout_seconds=10.0)
    res = await docker_runtime.run_command("touch /etc/malicious.txt", config=cfg)
    assert res.exit_code != 0
    assert "Read-only file system" in res.stderr or "Read-only" in res.stderr


@pytest.mark.asyncio
async def test_docker_security_network_isolated(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify that network access is completely disabled (network_mode='none')."""
    cfg = SandboxConfig(workspace_dir=temp_workspace, timeout_seconds=10.0)
    code = """
import urllib.request
try:
    urllib.request.urlopen("https://www.google.com", timeout=2)
    print("ONLINE")
except Exception as e:
    print(f"OFFLINE: {type(e).__name__}")
"""
    res = await docker_runtime.run_python(code, config=cfg)
    assert "OFFLINE" in res.stdout
    assert "ONLINE" not in res.stdout


@pytest.mark.asyncio
async def test_docker_security_docker_socket_not_mounted(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify that host Docker socket (/var/run/docker.sock) is never mounted."""
    cfg = SandboxConfig(workspace_dir=temp_workspace, timeout_seconds=10.0)
    res = await docker_runtime.run_command("test -e /var/run/docker.sock && echo 'EXISTS' || echo 'NOT_FOUND'", config=cfg)
    assert res.exit_code == 0
    assert "NOT_FOUND" in res.stdout


@pytest.mark.asyncio
async def test_docker_security_workspace_rw_mount(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify that workspace directory is mounted read-write and accessible to container."""
    cfg = SandboxConfig(workspace_dir=temp_workspace, timeout_seconds=10.0)
    code = """
with open("/workspace/generated.txt", "w") as f:
    f.write("sandbox-payload-12345")
print("WRITTEN")
"""
    res = await docker_runtime.run_python(code, config=cfg)
    assert res.exit_code == 0
    assert "WRITTEN" in res.stdout

    # Verify file exists on host workspace
    host_file = os.path.join(temp_workspace, "generated.txt")
    assert os.path.exists(host_file)
    with open(host_file, "r") as f:
        assert f.read() == "sandbox-payload-12345"


@pytest.mark.asyncio
async def test_docker_security_timeout_enforcement(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify that infinite loop/hanging code is terminated when timeout expires."""
    cfg = SandboxConfig(workspace_dir=temp_workspace, timeout_seconds=2.0)
    res = await docker_runtime.run_command("sleep 30", config=cfg)
    assert res.timed_out is True


@pytest.mark.asyncio
async def test_docker_security_output_truncation(docker_runtime: DockerSandboxRuntime, temp_workspace: str):
    """Verify that large output is truncated at max_output_bytes and flagged in metadata."""
    cfg = SandboxConfig(
        workspace_dir=temp_workspace,
        timeout_seconds=10.0,
        max_output_bytes=2048,  # 2KB bound
    )
    # Generate 50KB of text
    code = 'print("A" * 50000)'
    res = await docker_runtime.run_python(code, config=cfg)
    assert res.exit_code == 0
    assert res.metadata.get("truncated") is True
    assert "Output truncated" in res.stdout
    # Actual payload before notice should not exceed 2048 bytes
    assert len(res.stdout) < 4096
