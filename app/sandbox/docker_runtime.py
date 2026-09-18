"""Docker container sandbox runtime implementing isolated, non-root execution."""

import asyncio
import os
import time
import uuid
from typing import Optional

from app.core.errors import AURAError
from app.core.logging import logger
from app.sandbox.base import SandboxRuntime
from app.sandbox.spec import ExecutionResult, SandboxConfig

try:
    import docker
    from docker.errors import DockerException
except ImportError:
    docker = None
    DockerException = Exception


class DockerSandboxRuntime(SandboxRuntime):
    """
    Ephemeral container execution runtime leveraging Docker daemon.
    Enforces non-root privilege, read-only rootfs, disabled networking,
    strict resource quotas, and isolated workspace mounts.
    """

    def __init__(self) -> None:
        self._client: Optional["docker.DockerClient"] = None

    def _get_client(self) -> "docker.DockerClient":
        if docker is None:
            raise AURAError("Docker SDK is not installed.")
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def is_available(self) -> bool:
        """Check if Docker daemon is running and responsive."""
        if docker is None:
            return False
        try:
            client = self._get_client()
            return bool(client.ping())
        except Exception as e:
            logger.debug(f"Docker daemon ping failed: {e}")
            return False

    def _execute_sync(self, command_args: list[str], cfg: SandboxConfig) -> ExecutionResult:
        """Execute container synchronously in dedicated thread worker."""
        client = self._get_client()
        os.makedirs(cfg.workspace_dir, exist_ok=True)

        # Determine non-root container user matching workspace owner where supported
        container_user = cfg.user
        if os.name != "nt":
            try:
                # Ensure standard safe permissions (0o755: rwxr-xr-x), NEVER world-writable (0o777)
                os.chmod(cfg.workspace_dir, 0o755)
            except OSError:
                pass

            try:
                st = os.stat(cfg.workspace_dir)
                host_uid = st.st_uid
                host_gid = st.st_gid
                # If host workspace owner is non-root, match container user to workspace owner
                if host_uid != 0 and (cfg.user is None or cfg.user == "1000:1000"):
                    container_user = f"{host_uid}:{host_gid}"
            except Exception as e:
                logger.debug(f"Could not inspect host workspace owner UID/GID: {e}")

        volumes = {
            os.path.abspath(cfg.workspace_dir): {
                "bind": cfg.container_workspace_mount,
                "mode": "rw",
            }
        }

        # Convert cpu_quota to nano_cpus
        nano_cpus = int(cfg.cpu_quota * 1_000_000_000)

        container = None
        start_time = time.perf_counter()
        timed_out = False

        try:
            # Ensure image is present locally, pull if necessary
            try:
                client.images.get(cfg.image)
            except Exception:
                logger.info(f"Pulling Docker image '{cfg.image}'...")
                try:
                    client.images.pull(cfg.image)
                except Exception as pull_err:
                    logger.warning(f"Could not pull Docker image '{cfg.image}': {pull_err}")

            container = client.containers.create(
                image=cfg.image,
                command=command_args,
                volumes=volumes,
                working_dir=cfg.workdir,
                user=container_user,
                read_only=cfg.read_only_root,
                network_mode="none" if cfg.network_disabled else "bridge",
                mem_limit=cfg.memory_limit,
                nano_cpus=nano_cpus,
                pids_limit=cfg.pids_limit,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                environment=cfg.env,
                detach=True,
            )

            container.start()

            try:
                wait_res = container.wait(timeout=cfg.timeout_seconds)
                exit_code = wait_res.get("StatusCode", 0) if isinstance(wait_res, dict) else int(wait_res)
            except Exception as wait_err:
                logger.warning(f"Container wait exceeded timeout or failed: {wait_err}")
                timed_out = True
                try:
                    container.kill()
                except Exception:
                    pass
                exit_code = -1

            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Collect stdout and stderr with strict length bounds
            try:
                raw_stdout = container.logs(stdout=True, stderr=False)
                raw_stderr = container.logs(stdout=False, stderr=True)
            except Exception:
                raw_stdout, raw_stderr = b"", b""

            truncated = False
            if len(raw_stdout) > cfg.max_output_bytes:
                raw_stdout = raw_stdout[:cfg.max_output_bytes]
                truncated = True
            if len(raw_stderr) > cfg.max_output_bytes:
                raw_stderr = raw_stderr[:cfg.max_output_bytes]
                truncated = True

            stdout = raw_stdout.decode("utf-8", errors="replace")
            stderr = raw_stderr.decode("utf-8", errors="replace")

            meta: Dict[str, Any] = {"image": cfg.image, "container_id": container.id[:12]}
            if truncated:
                meta["truncated"] = True
                stdout += "\n... [Output truncated: exceeded max_output_bytes limit]"

            return ExecutionResult(
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                duration_ms=round(duration_ms, 2),
                metadata=meta,
            )

        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception as rem_err:
                    logger.warning(f"Error cleaning up ephemeral container: {rem_err}")

    async def run_command(self, command: str, config: Optional[SandboxConfig] = None) -> ExecutionResult:
        """Execute shell command inside container."""
        cfg = config or SandboxConfig()
        if not self.is_available():
            raise AURAError("Docker daemon is not available on this host.")

        command_args = ["sh", "-c", command]
        return await asyncio.to_thread(self._execute_sync, command_args, cfg)

    async def run_python(self, code: str, config: Optional[SandboxConfig] = None) -> ExecutionResult:
        """Execute inline Python code inside container via mounted script file."""
        cfg = config or SandboxConfig()
        if not self.is_available():
            raise AURAError("Docker daemon is not available on this host.")

        os.makedirs(cfg.workspace_dir, exist_ok=True)
        script_filename = f".sandbox_exec_{uuid.uuid4().hex[:8]}.py"
        host_script_path = os.path.join(cfg.workspace_dir, script_filename)
        container_script_path = f"{cfg.container_workspace_mount}/{script_filename}"

        # Write Python script into mounted workspace
        with open(host_script_path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            command_args = ["python", container_script_path]
            return await asyncio.to_thread(self._execute_sync, command_args, cfg)
        finally:
            if os.path.exists(host_script_path):
                try:
                    os.remove(host_script_path)
                except Exception:
                    pass
